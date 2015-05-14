# Copyright 2015 Cisco Systems, Inc.
# All rights reserved.
#
#    Licensed under the Apache License, Version 2.0 (the "License"); you may
#    not use this file except in compliance with the License. You may obtain
#    a copy of the License at
#
#         http://www.apache.org/licenses/LICENSE-2.0
#
#    Unless required by applicable law or agreed to in writing, software
#    distributed under the License is distributed on an "AS IS" BASIS, WITHOUT
#    WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied. See the
#    License for the specific language governing permissions and limitations
#    under the License.

"""BGP Update Message"""

import struct
import traceback
import logging

from ipaddr import IPv4Network

from yabgp.common import exception as excep
from yabgp.common import constants as bgp_cons
from yabgp.message.attribute import AttributeFlag
from yabgp.message.attribute.origin import Origin
from yabgp.message.attribute.aspath import ASPath
from yabgp.message.attribute.nexthop import NextHop
from yabgp.message.attribute.med import MED
from yabgp.message.attribute.localpref import LocalPreference
from yabgp.message.attribute.atomicaggregate import AtomicAggregate
from yabgp.message.attribute.aggregator import Aggregator
from yabgp.message.attribute.community import Community
from yabgp.message.attribute.originatorid import OriginatorID
from yabgp.message.attribute.clusterlist import ClusterList

LOG = logging.getLogger()


class Update(object):

    """
    An UPDATE message is used to advertise feasible routes that share
    common path attributes to a peer, or to withdraw multiple unfeasible
    routes from service (RFC 4271 page 15)
    """

    def __init__(self):
        """
        +----------------------------------------------------+
        |     Withdrawn Routes Length (2 octets)             |
        +----------------------------------------------------+
        |     Withdrawn Routes (variable)                    |
        +----------------------------------------------------+
        |     Total Path Attribute Length (2 octets)         |
        +----------------------------------------------------+
        |     Path Attributes (variable)                     |
        +----------------------------------------------------+
        |  Network Layer Reachability Information (variable) |
        +----------------------------------------------------+

        @ Withdrawn Routes Length:
            This 2-octets unsigned integer indicates the total length of
        the Withdrawn Routes field in octets. Its value allows the
        length of the Network Layer Reachability Information field to
        be determined, as specified below.
            A value of 0 indicates that no routes are being withdrawn from
        service, and that the WITHDRAWN ROUTES field is not present in
        this UPDATE message.

        @ Withdrawn Routes:
            This is a variable-length field that contains a list of IP
        address prefixes for the routes that are being withdrawn from
        service. Each IP address prefix is encoded as a 2-tuple of the
        form <length, prefix>, whose fields are described below:
                    +---------------------------+
                    |     Length (1 octet)      |
                    +---------------------------+
                    |     Prefix (variable)     |
                    +---------------------------+
            The use and the meaning of these fields are as follows:
            a) Length:
            The Length field indicates the length in bits of the IP
            address prefix. A length of zero indicates a prefix that
            matches all IP addresses (with prefix, itself, of zero
            octets).
            b) Prefix:
            The Prefix field contains an IP address prefix, followed by
            the minimum number of trailing bits needed to make the end
            of the field fall on an octet boundary. Note that the value
            of trailing bits is irrelevant.

        @ Total Path Attribute Length:
            This 2-octet unsigned integer indicates the total length of the
        Path Attributes field in octets. Its value allows the length
        of the Network Layer Reachability field to be determined as
        specified below.
            A value of 0 indicates that neither the Network Layer
        Reachability Information field nor the Path Attribute field is
        present in this UPDATE message.

        @ Path Attributes:
            (path attributes details see RFC 4271 and some other RFCs)

        @ Network Layer Reachability Information:
            This variable length field contains a list of IP address
        prefixes. The length, in octets, of the Network Layer
        Reachability Information is not encoded explicitly, but can be
        calculated as:
        UPDATE message Length - 23 - Total Path Attributes Length
        - Withdrawn Routes Length
        where UPDATE message Length is the value encoded in the fixedsize
        BGP header, Total Path Attribute Length, and Withdrawn
        Routes Length are the values encoded in the variable part of
        the UPDATE message, and 23 is a combined length of the fixedsize
        BGP header, the Total Path Attribute Length field, and the
        Withdrawn Routes Length field.
        Reachability information is encoded as one or more 2-tuples of
        the form <length, prefix>, whose fields are described below:
                    +---------------------------+
                    |      Length (1 octet)     |
                    +---------------------------+
                    |      Prefix (variable)    |
                    +---------------------------+
        The use and the meaning of these fields are as follows:
            a) Length:
                The Length field indicates the length in bits of the IP
            address prefix. A length of zero indicates a prefix that
            matches all IP addresses (with prefix, itself, of zero
            octets).
            b) Prefix:
                The Prefix field contains an IP address prefix, followed by
            enough trailing bits to make the end of the field fall on an
            octet boundary. Note that the value of the trailing bits is
            irrelevant.
        """

    def parse(self, msg):

        """
        Parse BGP Update message

        :param msg: raw BGP update binary PDU data
        :type msg: list
        :return: message after parsing.
        :return type: dict

        """
        t = msg[0]
        asn4 = msg[1]
        msg_hex = msg[2]

        results = {
            "Withdraw": None,
            "Attributes": None,
            "NLRI": None,
            'Time': t,
            'RawData': msg_hex,
            'SubError': None,
            'ErrorData': None}

        # get every part of the update message
        withdraw_len = struct.unpack('!H', msg_hex[:2])[0]
        withdraw_prefix_data = msg_hex[2:withdraw_len + 2]
        attr_len = struct.unpack('!H', msg_hex[withdraw_len + 2:withdraw_len + 4])[0]
        attribute_data = msg_hex[withdraw_len + 4:withdraw_len + 4 + attr_len]
        nlri_data = msg_hex[withdraw_len + 4 + attr_len:]

        try:
            # parse withdraw prefixes
            results['Withdraw'] = self.parse_prefix_list(withdraw_prefix_data)

            # parse nlri
            results['NLRI'] = self.parse_prefix_list(nlri_data)
        except Exception as e:
            LOG.error(e)
            error_str = traceback.format_exc()
            LOG.debug(error_str)
            results['SubError'] = bgp_cons.ERR_MSG_UPDATE_INVALID_NETWORK_FIELD
            results['ErrorData'] = ''
        try:
            # parse attributes
            results['Attributes'] = self.parse_attributes(attribute_data, asn4)
        except excep.UpdateMessageError as e:
            LOG.error(e)
            results['SubError'] = e.sub_error
            results['ErrorData'] = e.data
        except Exception as e:
            LOG.error(e)
            error_str = traceback.format_exc()
            LOG.debug(error_str)
            results['SubError'] = e
            results['ErrorData'] = e

        return results

    @staticmethod
    def parse_prefix_list(data):
        """
        Parses an RFC4271 encoded blob of BGP prefixes into a list

        :param data:
        :return: prefix_list
        """
        prefixes = []
        postfix = data
        while len(postfix) > 0:
            prefix_len = ord(postfix[0])
            if prefix_len > 32:
                LOG.warning('Prefix Length larger than 32')
            octet_len, remainder = prefix_len / 8, prefix_len % 8
            if remainder > 0:
                # prefix length doesn't fall on octet boundary
                octet_len += 1
            tmp = postfix[1:octet_len + 1]
            prefix_data = [ord(i) for i in tmp]
            # Zero the remaining bits in the last octet if it didn't fall
            # on an octet boundary
            if remainder > 0:
                prefix_data[-1] &= 255 << (8 - remainder)
            prefix_data = prefix_data + list(str(0)) * 4
            prefix = "%s.%s.%s.%s" % (tuple(prefix_data[0:4])) + '/' + str(prefix_len)
            prefixes.append(prefix)
            # Next prefix
            postfix = postfix[octet_len + 1:]

        return prefixes

    @staticmethod
    def parse_attributes(data, asn4=False):
        """
        Parses an RFC4271 encoded blob of BGP attributes into a list

        :param data:
        :param asn4: support 4 bytes asn or not
        :return:
        """
        attributes = {}
        postfix = data
        while len(postfix) > 0:

            try:
                flags, type_code = struct.unpack('!BB', postfix[:2])

                if flags & AttributeFlag.EXTENDED_LENGTH:
                    attr_len = struct.unpack('!H', postfix[2:4])[0]
                    attr_value = postfix[4:4 + attr_len]
                    postfix = postfix[4 + attr_len:]    # Next attribute
                else:    # standard 1-octet length
                    attr_len = ord(postfix[2])
                    attr_value = postfix[3:3 + attr_len]
                    postfix = postfix[3 + attr_len:]    # Next attribute
            except Exception as e:
                LOG.error(e)
                error_str = traceback.format_exc()
                LOG.debug(error_str)
                raise excep.UpdateMessageError(
                    sub_error=bgp_cons.ERR_MSG_UPDATE_MALFORMED_ATTR_LIST,
                    data='')

            if type_code == bgp_cons.BGPTYPE_ORIGIN:

                decode_value = Origin().parse(value=attr_value)

            elif type_code == bgp_cons.BGPTYPE_AS_PATH:

                decode_value = ASPath().parse(value=attr_value, asn4=asn4)

            elif type_code == bgp_cons.BGPTYPE_NEXT_HOP:

                decode_value = NextHop().parse(value=attr_value)

            elif type_code == bgp_cons.BGPTYPE_MULTI_EXIT_DISC:

                decode_value = MED().parse(value=attr_value)

            elif type_code == bgp_cons.BGPTYPE_LOCAL_PREF:

                decode_value = LocalPreference().parse(value=attr_value)

            elif type_code == bgp_cons.BGPTYPE_ATOMIC_AGGREGATE:

                decode_value = AtomicAggregate().parse(value=attr_value)

            elif type_code == bgp_cons.BGPTYPE_AGGREGATOR:

                decode_value = Aggregator().parse(value=attr_value, asn4=asn4)

            elif type_code == bgp_cons.BGPTYPE_COMMUNITIES:

                decode_value = Community().parse(value=attr_value)

            elif type_code == bgp_cons.BGPTYPE_ORIGINATOR_ID:

                decode_value = OriginatorID().parse(value=attr_value)

            elif type_code == bgp_cons.BGPTYPE_CLUSTER_LIST:

                decode_value = ClusterList().parse(value=attr_value)

            elif type_code == bgp_cons.BGPTYPE_NEW_AS_PATH:

                decode_value = ASPath().parse(value=attr_value, asn4=True)

            elif type_code == bgp_cons.BGPTYPE_NEW_AGGREGATOR:

                decode_value = Aggregator().parse(value=attr_value, asn4=True)
            else:
                decode_value = repr(attr_value)
            attributes[type_code] = decode_value

        return attributes

    @staticmethod
    def construct_header(msg):
        """
        Prepends the mandatory header to a constructed BGP message

        :param msg:
        :return:
        """
        #    16-octet     2-octet  1-octet
        # ---------------+--------+---------+------+
        #    Maker      | Length |  Type   |  msg |
        # ---------------+--------+---------+------+
        return struct.pack('!16sHB',
                           chr(255) * 16,
                           len(msg) + 19,
                           2) + msg

    @staticmethod
    def construct_prefix_v4(prefix_list):
        """
        constructs NLRI prefix list

        :param prefix_list: prefix list
        """
        nlri_raw_hex = ''
        for prefix in prefix_list:
            ip, masklen = prefix.split('/')
            ip_hex = IPv4Network(prefix).packed
            masklen = int(masklen)
            if 16 < masklen <= 24:
                ip_hex = ip_hex[0:3]
            elif 8 < masklen <= 16:
                ip_hex = ip_hex[0:2]
            elif masklen <= 8:
                ip_hex = ip_hex[0:1]
            nlri_raw_hex += struct.pack('!B', masklen) + ip_hex
        return nlri_raw_hex

    @staticmethod
    def encode_prefixes(prefixes):
        """Encodes a list of IPPrefix

        :param prefixes: prefix list"""

        prefix_data = ""
        for prefix in prefixes:
            octet_len, remainder = len(prefix) / 8, len(prefix) % 8
            if remainder > 0:
                # prefix length doesn't fall on octet boundary
                octet_len += 1
            prefix_data += struct.pack('!B', len(prefix)) + prefix.packed()[:octet_len]
        return prefix_data