#!/usr/bin/env python3

from blockingdict import BlockingDict
from ipaddress import IPv4Address, IPv4Interface, IPv4Network
from physical import Adapter, MultiportNode, BROADCAST_MAC, MARE_PROTONUM

FORMAT = 'qqh'


class EponaAdapter(Adapter):
    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        # Add any initialization you need below this line

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
            print('bad checksum')
            return

        #verify you are intended reciever 
        print(f'src hw addr {self.hwaddr}')
        print(f'broadcast MAC: {BROADCAST_MAC}')
        print(f'frame dest addr {frame[6:12]}')
        print(self.hwaddr == frame[6:12])
        
        if self.hwaddr != frame[6:12] and frame[6:12] != BROADCAST_MAC:
            print('wrong reciever')
            return

        print('correct recv')
        #send on network
        self.input(int.from_bytes(frame[12:14], 'big'), frame[15:])

    def output_ip(self, protonum, addr, dgram):
        """
        Called when the network layer wishes to transmit a datagram to a
        destination host.  Provides the protocol number, destination IPv4
        address as four bytes, and datagram contents as bytes.
        """
        pass


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
            print("Epona switch: failed checksum")
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
                print('EponaSwitch: dest prt matches src prt')
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