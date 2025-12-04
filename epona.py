#!/usr/bin/env python3

from blockingdict import BlockingDict
from ipaddress import IPv4Address, IPv4Interface, IPv4Network
from physical import Adapter, MultiportNode, BROADCAST_MAC, MARE_PROTONUM

FORMAT = 'qqh'


class EponaAdapter(Adapter):
    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        # Add any initialization you need below this line
        
        self.ip_map = BlockingDict() #IP -> MAC

    def output(self, protonum: int, dst, dgram):
        """
        Called when the network layer wishes to transmit a datagram to a
        destination host.  Provides the protocol number, destination MAC
        address, and datagram contents as bytes.
        """
        proto_bytes = protonum.to_bytes(2, 'big')
        checksum = get_checksum(self.hwaddr + dst + proto_bytes + dgram)
        self.tx(self.hwaddr + dst + proto_bytes + checksum + dgram)
        

    def rx(self, frame: bytes):
        """
        Called when a frame arrives at the adapter.  Provides the frame
        contents as bytes.
        """
        
        if not verify_checksum(frame):
            #drop frame
            return

        protonum = int.from_bytes(frame[12:14], 'big')
        
        #handle MARE
        if protonum == MARE_PROTONUM:
            reply_code = frame[19] #realizing I can prob infer this from whether its broadcast or not
            src_mac = frame[:6]

            ip_bytes = frame[15:19]
            
            #is it a request or reply?
            if reply_code == 0: #request
                                
                ip = IPv4Address(ip_bytes)
                
                #if request for this ip --> send reply
                if ip == self.iface.ip:
                    reply_flag = 1
                    mare_bytes: bytes = ip_bytes + reply_flag.to_bytes(1, 'big')

                    self.output(MARE_PROTONUM, src_mac, mare_bytes)
            else: #reply
                self.ip_map.put(ip_bytes, src_mac)
            return


        #NON-MARE handling
        #verify you are intended reciever 
        if self.hwaddr != frame[6:12] and frame[6:12] != BROADCAST_MAC:
            return

        #send on network
        self.input(int.from_bytes(frame[12:14], 'big'), frame[15:])

    def output_ip(self, protonum, addr, dgram):
        """
        Called when the network layer wishes to transmit a datagram to a
        destination host.  Provides the protocol number, destination IPv4
        address as four bytes, and datagram contents as bytes.
        """
        #first check for in network
        ip = IPv4Address(addr)

        #send to gateway if not in network
        if ip not in self.iface.network: 
            addr = self.gateway.packed #convert to bytes
        
        ##initial check
        mac_addr = self.ip_map.get(addr, timeout=0.1)

        #we have the mapping
        if mac_addr != None:
           self.output(protonum, mac_addr, dgram)
           return 
        
        reply_flag: int = 0
        mare_bytes: bytes =  addr + reply_flag.to_bytes(1, 'big')

        to_count = 0
        while(to_count < 2):
            
            #we do not have the mac addr --> broadcast
            self.output(MARE_PROTONUM, BROADCAST_MAC, mare_bytes) #need to send ip addr for MARE protocol
            
            #resend if we dont get it
            mac_addr = self.ip_map.get(key=addr,timeout=0.1)
            if mac_addr == None:
                to_count += 1
                continue
            else:
                self.output(protonum, mac_addr, dgram)
                return
            
        raise self.NoRouteToHost



class EponaSwitch(MultiportNode):
    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        # Add any initialization you need below this line
        self.frame_map = {}

    def rx(self, port, frame):
        """
        Called when a frame arrives at any port.  Provides the port number as
        an int and the frame contents as bytes.
        """

        #verify checksum
        if not verify_checksum(frame):
            #print("Epona switch: failed checksum")
            return
        
        #extract fields 
        src = frame[:6]
        dest = frame[6:12]
        protonum = frame[12:14]
        data = frame[15:]

        self.frame_map[src] = port #store mapping 
        dest_port = self.frame_map.get(dest)

        #handle specific dest that isn't itself
        if dest_port != None:

            #drop frames frwrd to itself
            if dest_port == port:
                #print('EponaSwitch: dest prt matches src prt')
                return

            self.forward(dest_port, frame)
        #handle broadcast
        else:

            #send to all ports excluding current port
            for p in range(self.nports): 
                if p != port:
                    self.forward(p, frame)
        


def get_checksum(precheck: bytes):
    """Return 1-byte checksum as bytes object."""
    checksum_val = (~(sum(precheck) & 0xFF)) & 0xFF  # invert and mask to 1 byte

    return bytes([checksum_val])

def verify_checksum(segment: bytes):
    """Verify simple 1-byte checksum."""
    total = sum(segment) & 0xFF
    return total == 0xFF