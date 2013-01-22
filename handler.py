#!/usr/bin/env python
# -*- coding: utf-8 -*-

'''
Handle RTMP messaging which type is audio or video.
'''

from StringIO import StringIO
import os, struct

_TAG_TYPE_AAC = 8
_TAG_TYPE_H264 = 9

_FLV_SOUND_FORMAT_AAC = 10 # AAC
_FLV_VIDEO_FORMAT_AVC = 7 # H.264

_FLV_KEY_FRAME = 1 # key frame (for AVC, a seekable frame)
# 2 = inter frame (for AVC, a non-seekable frame)
# 3 = disposable inter frame (H.263 only)
# 4 = generated key frame (reserved for server use only)
# 5 = video info/command frame

_MASKS = (0x80, 0x40, 0x20, 0x10, 0x08, 0x04, 0x02, 0x01)

_VIDEO_PID = 0x0100
_AUDIO_PID = 0x0101

def to_pts_only(pts):
    # '0010' PTS[32..30] '1' | PTS[29..22] | PTS[21..15] '1' | PTS[14..7] | PTS[6..0] '1'
    # 0010 3 bit: ###1 | 8 bit: #### #### | 7 bit: #### ###1 | 8 bit: #### #### | 7 bit: #### ###1
    # 0010 xxx1 = 0x21, 0x0e
    p0 = 0x21 | ((pts >> 29) & 0x0e)
    # xxxx xxxx | xxxx xxx1
    p1 = 0x0001 | ((pts >> 14) & 0xfffe)
    # xxxx xxxx | xxxx xxx1
    p2 = 0x0001 | ((pts << 1) & 0xfffe)
    # >BHH
    return (p0, p1, p2)

def to_pts_dts(pts):
    # '0011' PTS[32..30] '1' | PTS[29..22] | PTS[21..15] '1' | PTS[14..7] | PTS[6..0] '1'
    # 0011 xxx1 = 0x31, 0x0e
    p0 = 0x31 | ((pts >> 29) & 0x0e)
    # xxxx xxxx | xxxx xxx1
    p1 = 0x0001 | ((pts >> 14) & 0xfffe)
    # xxxx xxxx | xxxx xxx1
    p2 = 0x0001 | ((pts << 1) & 0xfffe)
    dts = pts - 63000
    # '0001' DTS[32..30] '1' | DTS[29..22] | DTS[21..15] '1' | DTS[14..7] | DTS[6..0] '1'
    # 0001 xxx1 = 0x31, 0x0e
    d0 = 0x11 | ((dts >> 29) & 0x0e)
    # xxxx xxxx | xxxx xxx1
    d1 = 0x0001 | ((dts >> 14) & 0xfffe)
    # xxxx xxxx | xxxx xxx1
    d2 = 0x0001 | ((dts << 1) & 0xfffe)
    # >BHHBHH
    return (p0, p1, p2, d0, d1, d2)

class TagData(object):

    def __init__(self, tag_type, is_iframe, timestamp, data):
        self.tag_type = tag_type
        self.is_iframe = is_iframe
        self.timestamp = timestamp
        self._data = [data]
        self.length = len(data)

    def append(self, data):
        self._data.append(data)
        self.length = self.length + len(data)

    @property
    def data(self):
        return ''.join(self._data)

class TagCollector(object):
    def __init__(self):
        self._tags = []

    def append(self, tag_type, is_iframe, timestamp, data):
        print 'Append tag for', 'V' if tag_type==_TAG_TYPE_H264 else 'A', 'timestamp:', timestamp, 'size =', len(data)
        if self._tags and not is_iframe:
            last = self._tags[-1]
            if last.tag_type==tag_type and (last.length + len(data)) < 4100:
                last.append(data)
                return
        self._tags.append(TagData(tag_type, is_iframe, timestamp, data))

    def pop_to(self, timestamp):
        n = 0
        for t in self._tags:
            if t.timestamp > timestamp:
                break
            n = n + 1
        L = self._tags[:n]
        self._tags = self._tags[n:]
        return L

def hexline(s):
    n = 0
    for ch in s:
        n = n + 1
        s = hex(ord(ch))[2:] # remove prefix '0x'
        if len(s)==1:
            s = '0' + s
        print s,
        if n % 16==0:
            print
    print

class TSWriter(object):

    def __init__(self, pid, stream_id):
        self._ccounter = 0x00
        self._pid = pid
        self._stream_id = stream_id

    def reset_ccounter(self):
        self._ccounter = 0

    def _create_pes(self, tag):
        pts = tag.timestamp * 90 + 126000
        if tag.tag_type == 1111: #_TAG_TYPE_H264:
            p0, p1, p2, d0, d1, d2 = to_pts_dts(pts)
            packet_length = len(tag.data) + 13
            # PES Start code 000001 | StreamID | Packet Length 16 bit | ignore 0x80 | flag 0xc0 | header_data_length 8 bit = 0x0a | PTS 5 bytes | DTS 5 bytes | payload body...
            return struct.pack('>BBBBHBBBBHHBHH', 0x00, 0x00, 0x01, self._stream_id, packet_length, 0x80, 0xc0, 0x0a, p0, p1, p2, d0, d1, d2) + tag.data
        else:
            p0, p1, p2 = to_pts_only(pts)
            packet_length = len(tag.data) + 8
            print 'Data length:', len(tag.data), 'Packet:', packet_length
            # PES Start code 000001 | StreamID | Packet Length 16 bit | ignore 0x80 | flag 0x80 | header_data_length 8 bit = 0x05 | PTS 5 bytes | payload body...
            return struct.pack('>BBBBHBBBBHH', 0x00, 0x00, 0x01, self._stream_id, packet_length, 0x80, 0x80, 0x05, p0, p1, p2) + tag.data

    def writeTS(self, fp, tag):
        print '# write ts for video?', tag.tag_type==_TAG_TYPE_H264, ', timestamp:', tag.timestamp
        pusi = True
        pes = self._create_pes(tag)
        print 'PES header:'
        hexline(pes[:14])
        data_remaining = pes_length = len(pes)
        pcr_base = tag.timestamp * 90 + 63000
        pcr_ext = (tag.timestamp * 270) % 300
        while data_remaining > 0:
            fp.write('\x47')
            ts_remaining = 187
            fill_ffs = 0
            if pusi:
                pusi = False
                # error_indicator = 0 | payload_unit_start_indicator = 1 | transport_priority = 0 | PID = 13 bit
                # 010x xxxx | xxxx xxxx
                i16 = 0x4000 | (self._pid & 0x1fff)
                # scrambling_control = 00 | adaptation_field_control = 11 | continuity_counter = 4 bit
                # 0011 xxxx
                i8 = 0x30 | self._ccounter
                # adaption field length = ?
                af_length = 0x07
                # flag = DI, RI, EI, PCR_F, OPCR_F, SF, TF, AF = 01010000 = 0x50
                flag = 0x50
                # PCR_base 33 bit | reserved = 6 bit | PCR_extension = 9 bit
                # xxxx xxxx | xxxx xxxx | xxxx xxxx | xxxx xxxx | x111 111x | xxxx xxxx
                pcr32_1 = pcr_base >> 1
                pcr8_2 = (pcr_base & 0x01 << 7) | 0x7e | ((pcr_ext >> 8) & 0x01)
                pcr8_3 = pcr_ext & 0xff
                ts_remaining = ts_remaining - 11
                if ts_remaining > data_remaining:
                    # not enough data, so add af_length and fill with 0xff...
                    fill_ffs = ts_remaining - data_remaining
                    af_length = af_length + fill_ffs
                fp.write(struct.pack('>HBBBLBB', i16, i8, af_length, flag, pcr32_1, pcr8_2, pcr8_3))
                if fill_ffs > 0:
                    fp.write('\xff' * fill_ffs)
                    ts_remaining = ts_remaining - fill_ffs
                fp.write(pes[pes_length - data_remaining : pes_length - data_remaining + ts_remaining])
                data_remaining = data_remaining - ts_remaining
            else:
                # error_indicator = 0 | payload_unit_start_indicator = 0 | transport_priority = 0 | PID = 13 bit
                # 000x xxxx | xxxx xxxx
                i16 = 0x1fff & (self._pid & 0x1fff)
                fp.write(chr(i16 >> 8))
                fp.write(chr(i16 & 0xff))
                ts_remaining = ts_remaining - 2
                # should have adaption field?
                if (ts_remaining - 1) <= data_remaining:
                    # no adaption field: transport_scrambling_control = 00 | adaptation_field_control = 01 | continuity_counter
                    fp.write(chr(0x10 | self._ccounter))
                    ts_remaining = ts_remaining - 1
                    fp.write(pes[pes_length - data_remaining : pes_length - data_remaining + ts_remaining])
                    data_remaining = data_remaining - ts_remaining
                else:
                    # must have at least 1 byte of adaption field: transport_scrambling_control = 00 | adaptation_field_control = 11 | continuity_counter
                    fp.write(chr(0x30 | self._ccounter))
                    ts_remaining = ts_remaining - 1
                    af_length = ts_remaining - data_remaining - 1
                    fp.write(chr(af_length))
                    ts_remaining = ts_remaining - 1 - af_length
                    if af_length > 0:
                        # write flag and extra 0xff...
                        fp.write('\x00')
                        af_length = af_length - 1
                        while af_length > 0:
                            fp.write('\xff')
                            af_length = af_length - 1
                    fp.write(pes[pes_length - data_remaining : pes_length - data_remaining + ts_remaining])
                    data_remaining = data_remaining - ts_remaining
            self._ccounter = (self._ccounter + 1) & 0x0f

class H264Parser(TSWriter):

    def __init__(self, tag_collector):
        super(H264Parser, self).__init__(_VIDEO_PID, 0xe0)
        self._tag_collector = tag_collector
        self._pps = []
        self._sps = []
        self._nalu_length_size = 0

    def parse(self, s):
        #print '---------- H264 ----------'
        length = s.read_uint24()
        timestamp = s.read_uint24()
        extend_ts = s.read_uint8()
        ts = timestamp + (extend_ts << 24)
        stream_id = s.read_uint24()
        videoTagHeader = s.read_uint8()
        if (videoTagHeader & 0x0f) != _FLV_VIDEO_FORMAT_AVC:
            raise FLVError('Bad video format: not H264.')
        frameType = (videoTagHeader & 0xf0) >> 4
        #print 'Frame type (1=I, 2=P):', frameType
        AVCPacketType = s.read_uint8()
        #print 'avc packet type (0=seq header, 1=NALU, 2=end seq):', AVCPacketType
        compositionTime = s.read_uint24()
        #print 'composition time (in ms):', compositionTime
        if AVCPacketType==0:
            # See ISO 14496-15, 5.2.4.1 for the description of AVCDecoderConfigurationRecord.
            # This contains the same information that would be stored in an avcC box in an MP4/FLV file.
            print 'Parse AVCDecoderConfigurationRecord'
            self._parse_config_record(s)
            # add SPS and PPS NALUs:
            nalus = []
            nalus.extend(self._sps)
            nalus.extend(self._pps)
            self._tag_collector.append(_TAG_TYPE_H264, True, ts, ''.join(nalus))
        elif AVCPacketType==1:
            # One or more NALUs (Full frames are required)
            self._tag_collector.append(_TAG_TYPE_H264, frameType==_FLV_KEY_FRAME, ts, self._parse_NALUs(s))
        elif AVCPacketType==2:
            # end of video:
            print 'END of video'
        else:
            raise FLVError('Bad AVCPacketType: %d' % AVCPacketType)
        return ts, frameType==_FLV_KEY_FRAME # True if I-frame

    def _parse_config_record(self, s):
        # config_version:
        ver = s.read_uint8()
        if ver != 1:
            raise FLVError('Bad config version in AVCDecoderConfigurationRecord: %d' % ver)
        avc_profile_indication = s.read_uint8()
        print 'profile:', avc_profile_indication
        profile_compatibility = s.read_uint8()
        avc_level_indication = s.read_uint8()
        length_size_minus_one = s.read_uint8() & 0x03
        print 'length_size_minus_one:', length_size_minus_one
        num_of_sps = s.read_uint8() & 0x1f
        print 'num_of_sps:', num_of_sps
        for i in range(num_of_sps):
            sps_length = s.read_uint16()
            spsNALU = s.read_bytes(sps_length)
            print 'spsNALU Length:', sps_length
            print 'spsNALU:', hex(ord(spsNALU[0]))
            self._sps.append('\x00\x00\x00\x01' + spsNALU)
        num_of_pps = s.read_uint8()
        print 'num_of_pps:', num_of_pps
        for i in range(num_of_pps):
            pps_length = s.read_uint16()
            ppsNALU = s.read_bytes(pps_length)
            print 'ppsNALU Length:', pps_length
            print 'ppsNALU:', hex(ord(ppsNALU[0]))
            self._pps.append('\x00\x00\x00\x01' + ppsNALU)
        self._nalu_length_size = length_size_minus_one + 1
        print 'data available:', s.available()

    def _parse_NALUs(self, s):
        nalu_length_size = self._nalu_length_size
        if nalu_length_size==0:
            raise FLVError('Cannot parse NALU because AVCDecoderConfigurationRecord was not parsed.')
        # the max value of nalu_length_size is 4 (=0x03 + 1)
        length = 0
        if nalu_length_size==4:
            length = s.read_uint32()
        elif nalu_length_size==3:
            length = s.read_uint24()
        elif nalu_length_size==2:
            length = s.read_uint16()
        else:
            length = s.read_uint8()
        data_available = s.available()
        if data_available<length:
            raise FLVError('bad NALU length.')
        return '\x00\x00\x00\x01' + s.read_bytes(length)

# AAC ADTS Header 7 bytes
# syncword, ID, layer, protection_absent
# | ssss ssss | ssss illp |
# profile, sampling, private_bit, channel_conf original_copy, home, copyright_id_bit, copy_start,
# aac_frame_length, buffer_fullness, number_of_raw_data_blocks
# | ppss sspc ccoh ccll llll llll lllb bbbb bbbb bbnn |

class AACParser(TSWriter):

    def __init__(self, tag_collector):
        super(AACParser, self).__init__(_AUDIO_PID, 0xc0)
        self._tag_collector = tag_collector
        self._adts_header = None

    def parse(self, s):
        #print '---------- AAC ----------'
        length = s.read_uint24()
        timestamp = s.read_uint24()
        extend_ts = s.read_uint8()
        ts = timestamp + (extend_ts << 24)
        stream_id = s.read_uint24()
        b = s.read_uint8()
        if ((b & 0xf0) >> 4) != _FLV_SOUND_FORMAT_AAC:
            raise FLVError('Bad audio format: not AAC.')
        sound_rate = (b & 0x0c) >> 2
        sound_sample = (b & 0x02) >> 1
        sound_type = b & 0x01
        # AACPacketType:
        if s.read_uint8()==0:
            self._adts_header = self._parse_aac_sequence(s)
            print 'AAC sequence header:', self._adts_header
        else:
            if self._adts_header:
                raw = self._parse_aac_raw(s)
                self._tag_collector.append(_TAG_TYPE_AAC, False, ts, raw)
            else:
                print 'ERROR: no adts header but meet raw!'
        return ts

    def _parse_aac_raw(self, s):
        payload = s.left()
        # aac frame size = ADTS_HEADER_SIZE (7 bytes) + payload size
        size = 7 + len(payload)
        # 13 bits size:
        c3, c5 = ord(self._adts_header[3]), ord(self._adts_header[5])
        i3 = ((size & 0x1800) >> 11) | (c3 & 0xfc)
        i4 = (size & 0x07f8) >> 3
        i5 = ((size & 0x07) << 5) | (c5 & 0x1f)
        return struct.pack('>sssBBBs', self._adts_header[0], self._adts_header[1], self._adts_header[2], i3, i4, i5, self._adts_header[6]) + payload

    def _parse_aac_sequence(self, s):
        #print '[FRAME]'
        b1 = s.read_uint8()
        b2 = s.read_uint8()
        aac_object_type = (b1 & 0xf8) >> 3
        print 'aac_object_type (0=main, 1=lc, 2=ssr, 3=LTP):', aac_object_type
        # it seems only object-type==01 can be played, so fix to 01:
        if aac_object_type!=1:
            print 'FIXME: set aac_object_type = 1'
            aac_object_type = 1

        aac_sampling_freq = ((b1 & 0x03) << 1) + ((b2 & 0x80) >> 7)
        print 'aac_sampling_freq (0=96,1=88,2=64,3=48,4=44,5=32...):', aac_sampling_freq

        aac_channel_conf = (b2 & 0x78) >> 3
        print 'aac_channel_conf:', aac_channel_conf
        aac_frame_length_conf = (b2 & 0x04) >> 2
        print 'aac_frame_length_conf (always 0):', aac_frame_length_conf
        aac_depends_coder = (b2 & 0x02) >> 1
        print 'aac_depends_coder (always 0):', aac_depends_coder
        aac_extension_flag = b2 & 0x01
        print 'aac_extension_flag', aac_extension_flag

        # generate ADTS:
        pb = PutBits()
        pb.put(12, 0xfff)            # syncword
        pb.put(1, 0)                 # ID
        pb.put(2, 0)                 # layer
        pb.put(1, 1)                 # protection absent
        pb.put(2, aac_object_type)   # profile object type
        pb.put(4, aac_sampling_freq) # sample rate index
        pb.put(1, 0)                 # private bit
        pb.put(3, aac_channel_conf)  # channel conf
        pb.put(1, 0)                 # original copy
        pb.put(1, 0)                 # home

        pb.put(1, 0)                 # copyright identification bit
        pb.put(1, 0)                 # copyright identification start
        pb.put(13, 0)                # aac frame length = ADTS_HEADER_SIZE + size + pce_size, set by each frame
        pb.put(11, 0x7ff)            # adts buffer fullness
        pb.put(2, 0)                 # number of raw data blocks in frame
        return pb.value()

class BytesIO(object):

    def __init__(self, data):
        self._data = data
        self._position = 0
        self._length = len(data)

    def read_uint8(self):
        if self._position >= self._length:
            raise IOError('EOF of BytesIO')
        n = ord(self._data[self._position])
        self._position = self._position + 1
        return n

    def read_uint16(self):
        return (self.read_uint8() << 8) + self.read_uint8()

    def read_uint24(self):
        return (self.read_uint8() << 16) + (self.read_uint8() << 8) + self.read_uint8()

    def read_uint32(self):
        return (self.read_uint8() << 24) + (self.read_uint8() << 16) + (self.read_uint8() << 8) + self.read_uint8()

    def read_uint64(self):
        return (self.read_uint8() << 56) + (self.read_uint8() << 48) + (self.read_uint8() << 40) + (self.read_uint8() << 32) + (self.read_uint8() << 24) + (self.read_uint8() << 16) + (self.read_uint8() << 8) + self.read_uint8()

    def read_bytes(self, n):
        if self._position + n > self._length:
            raise IOError('Skip n bytes cause EOF.')
        start = self._position
        self._position = self._position + n
        return self._data[start:self._position]

    def available(self):
        return self._length - self._position

    def skip(self, n):
        if self._position + n > self._length:
            raise IOError('Skip n bytes cause EOF.')
        self._position = self._position + n

    def left(self):
        return self._data[self._position:]

    def __getitem__(self, key):
        return self._data[key]

class FLVError(StandardError):
    pass

class PutBits(object):
    def __init__(self):
        self._bytes = []

    def put(self, size, value):
        for i in range(size-1, -1, -1):
            v = value & (0x01 << i)
            self._bytes.append(1) if v else self._bytes.append(0)

    def value(self):
        '''
        return value as str. e.g.:
        FLV = 46 4c 56 = 01000110 01001100 01010110
                       = 010 0011001 001 1000 1010 110

        >>> pb = PutBits()
        >>> pb.put(3, 0x2)
        >>> pb.put(7, 0x19)
        >>> pb.put(3, 0x1)
        >>> pb.put(4, 0x8)
        >>> pb.put(4, 0xa)
        >>> pb.put(3, 0x6)
        >>> pb.value()
        'FLV'
        '''
        mod = len(self._bytes) % 8
        if mod != 0:
            print 'WARNING: need append bits!'
            for i in range(mod):
                self._bytes.append(0)
        n = 0
        v = 0
        s = ''
        for i in self._bytes:
            if i:
                v = v | _MASKS[n]
            n = n + 1
            if n==8:
                s = s + chr(v)
                v = 0
                n = 0
        return s

class TsHandler(object):

    def __init__(self, segment_interval=3000):
        self._segment_interval = segment_interval
        self._check_interval = segment_interval + 1000
        self._counter = 0
        self._tag_collector = TagCollector()
        self._aacparser = AACParser(self._tag_collector)
        self._h264parser = H264Parser(self._tag_collector)

        ps = PacketStream()
        ps.writePAT()
        self._pat = ps.getvalue()
        ps = PacketStream()
        ps.writePMT()
        self._pmt = ps.getvalue()
        self._start_timestamp = None

    def processTag(self, data, processVideo=True, processAudio=True):
        self._counter = self._counter + 1
        #fp = open('/Users/michael/Github/rtmp-livestreaming/tmp/flv/%05d.tag' % self._counter, 'w+b')
        #fp.write(data)
        #fp.close()
        s = BytesIO(data)
        tag_type = s.read_uint8() & 0x1f
        ts = 0
        is_iframe = False
        if tag_type == _TAG_TYPE_AAC and processAudio:
            ts = self._aacparser.parse(s)
        elif tag_type == _TAG_TYPE_H264 and processVideo:
            ts, is_iframe = self._h264parser.parse(s)
        else:
            return
        if True:
            return
        if self._start_timestamp is None:
            self._start_timestamp = ts
            print 'Initial start: %s' % self._start_timestamp
        else:
            if is_iframe and (ts - self._start_timestamp) >= self._segment_interval:
                print '#############################'
                print '# Make a segment: TS =', ts, 'start =', self._start_timestamp
                print '# Interval = %d' % (ts - self._start_timestamp)
                print '#############################'
                tags = self._tag_collector.pop_to(ts)
                self._start_timestamp = ts
                print 'set new start = %d' % self._start_timestamp
                self._write_ts_segment(tags)

    def endProcess(self):
        print 'END'

    def _write_ts_segment(self, tags):
        if hasattr(self, 'segment_index'):
            self.segment_index = self.segment_index + 1
        else:
            self.segment_index = 0
        with open('/Users/michael/Github/rtmp-livestreaming/tmp/segments/%05d.ts' % self.segment_index, 'w+b') as f:
            print '### write ts segment', self.segment_index
            f.write(self._pat)
            f.write(self._pmt)
            self._aacparser.reset_ccounter()
            self._h264parser.reset_ccounter()
            print '# write', len(tags), 'tags'
            for tag in tags:
                if tag.tag_type==_TAG_TYPE_AAC:
                    try:
                        self._aacparser.writeTS(f, tag)
                    except BaseException, e:
                        print e
                elif tag.tag_type==_TAG_TYPE_H264:
                    self._h264parser.writeTS(f, tag)
                else:
                    raise StandardError('Should never go here')

class PacketStream(object):

    def __init__(self):
        self._buffer = StringIO()

    def getvalue(self):
        return self._buffer.getvalue()

    def writePES(self, pid, stream_id, data):
        # packet with pusi=1:
        self._write_header(pusi=1, pid=pid, af=0x03, ccounter=0)
        # write adaption fields length = 0x07:
        self._buffer.write('\x07')
        # write adaption flags = 0x50 '0101 0000'
        self._buffer.write('\x50')

    def writePAT(self):
        self._write_header(pusi=1, pid=0, af=0x01)
        # write pointer = 0x00, tableID = 0x00:
        self._buffer.write('\x00\x00')
        # write:
        #   section_syntax_indicator = 1 (1 bit),
        #   '0' (1 bit)
        #   reserved 00 (2 bit)
        #   section_length (12 bit, but only use lower 8 bit:
        self._buffer.write('\xb0') # 10110000
        self._buffer.write('\x0d') # section_length = 13 including CRC32
        # write transport_tream_id = 1 (2 bytes):
        self._buffer.write('\x00\x01')
        # write:
        #   reserved = 11 (2 bit)
        #   version number = 0 (5 bit)
        #   current_next_indicator = 1 (1 bit)
        self._buffer.write('\xc1') # 11000001
        # write section_number = 0 (8 bit), last_section_number = 0 (8 bit):
        self._buffer.write('\x00\x00')
        # write only 1 program, program_number = 1:
        self._buffer.write('\x00\x01')
        # write reserved=111 (3 bit) + program_map_PID=0x1000 (13 bit):
        self._buffer.write('\xf0\x00')
        # write CRC:
        self._buffer.write(crc32(self._buffer.getvalue()[5:]))
        # fill with 0xff:
        self._fill_ffs()

    def writePMT(self):
        self._write_header(pusi=1, pid=0x1000, af=0x01)
        # write pointer = 0x00, tableID = 0x02:
        self._buffer.write('\x00\x02')
        # write:
        #   section_syntax_indicator = 1 (1 bit),
        #   '0' (1 bit)
        #   reserved 00 (2 bit)
        #   section_length (12 bit, but only use lower 8 bit:
        self._buffer.write('\xb0') # 10110000
        self._buffer.write('\x17') # section_length = 23 including CRC32
        # write only 1 program, program_number = 1:
        self._buffer.write('\x00\x01')
        # write:
        #   reserved = 11 (2 bit)
        #   version number = 0 (5 bit)
        #   current_next_indicator = 1 (1 bit)
        self._buffer.write('\xc1') # 11000001
        # write section_number = 0 (8 bit), last_section_number = 0 (8 bit):
        self._buffer.write('\x00\x00')
        # write:
        #   reserved = 111 (3 bit)
        #   PCR_PID = 0x0100 = 00001 00000000 (13 bit)
        self._buffer.write('\xe1\x00')
        # write:
        #   reserved = 1111 (4 bit)
        #   program_info_length = 0 (12 bit)
        self._buffer.write('\xf0\x00')
        # write H264 Video:
        #   stream_type = 0x1b (8 bit)
        #   reserved = 111 (3 bit)
        #   elementary_PID = 00001 00000000 (13 bit)
        #   reserved = 1111 (4 bit)
        #   ES_info_length = 0 (12 bit)
        self._buffer.write('\x1b\xe1\x00\xf0\x00')
        # write AAC Audio:
        #   stream_type = 0x0f (8 bit)
        #   reserved = 111 (3 bit)
        #   elementary_PID = 00001 00000001 (13 bit)
        #   reserved = 1111 (4 bit)
        #   ES_info_length = 0 (12 bit)
        self._buffer.write('\x0f\xe1\x01\xf0\x00')
        # write CRC:
        self._buffer.write(crc32(self._buffer.getvalue()[5:]))
        # fill with 0xff:
        self._fill_ffs()

    def _fill_ffs(self):
        n = 188 - self._buffer.len
        if n>0:
            self._buffer.write('\xff' * n)

    def _write_header(self, pusi, pid, af, ccounter=0):
        # pusi=1 or 0:
        b1 = (pusi << 6) | ((pid & 0x1fff) >> 8) # pid higher 5 bit
        b2 = pid & 0xff # lower 8 bit
        # adaption_field=0x01, 0x02, 0x03:
        b3 = (af << 4) | (ccounter & 0x0f)
        self._buffer.write('\x47')
        self._buffer.write(chr(b1))
        self._buffer.write(chr(b2))
        self._buffer.write(chr(b3))

_CRC32 = [
        0x00000000, 0x04c11db7, 0x09823b6e, 0x0d4326d9,
        0x130476dc, 0x17c56b6b, 0x1a864db2, 0x1e475005,
        0x2608edb8, 0x22c9f00f, 0x2f8ad6d6, 0x2b4bcb61,
        0x350c9b64, 0x31cd86d3, 0x3c8ea00a, 0x384fbdbd,
        0x4c11db70, 0x48d0c6c7, 0x4593e01e, 0x4152fda9,
        0x5f15adac, 0x5bd4b01b, 0x569796c2, 0x52568b75,
        0x6a1936c8, 0x6ed82b7f, 0x639b0da6, 0x675a1011,
        0x791d4014, 0x7ddc5da3, 0x709f7b7a, 0x745e66cd,
        0x9823b6e0, 0x9ce2ab57, 0x91a18d8e, 0x95609039,
        0x8b27c03c, 0x8fe6dd8b, 0x82a5fb52, 0x8664e6e5,
        0xbe2b5b58, 0xbaea46ef, 0xb7a96036, 0xb3687d81,
        0xad2f2d84, 0xa9ee3033, 0xa4ad16ea, 0xa06c0b5d,
        0xd4326d90, 0xd0f37027, 0xddb056fe, 0xd9714b49,
        0xc7361b4c, 0xc3f706fb, 0xceb42022, 0xca753d95,
        0xf23a8028, 0xf6fb9d9f, 0xfbb8bb46, 0xff79a6f1,
        0xe13ef6f4, 0xe5ffeb43, 0xe8bccd9a, 0xec7dd02d,
        0x34867077, 0x30476dc0, 0x3d044b19, 0x39c556ae,
        0x278206ab, 0x23431b1c, 0x2e003dc5, 0x2ac12072,
        0x128e9dcf, 0x164f8078, 0x1b0ca6a1, 0x1fcdbb16,
        0x018aeb13, 0x054bf6a4, 0x0808d07d, 0x0cc9cdca,
        0x7897ab07, 0x7c56b6b0, 0x71159069, 0x75d48dde,
        0x6b93dddb, 0x6f52c06c, 0x6211e6b5, 0x66d0fb02,
        0x5e9f46bf, 0x5a5e5b08, 0x571d7dd1, 0x53dc6066,
        0x4d9b3063, 0x495a2dd4, 0x44190b0d, 0x40d816ba,
        0xaca5c697, 0xa864db20, 0xa527fdf9, 0xa1e6e04e,
        0xbfa1b04b, 0xbb60adfc, 0xb6238b25, 0xb2e29692,
        0x8aad2b2f, 0x8e6c3698, 0x832f1041, 0x87ee0df6,
        0x99a95df3, 0x9d684044, 0x902b669d, 0x94ea7b2a,
        0xe0b41de7, 0xe4750050, 0xe9362689, 0xedf73b3e,
        0xf3b06b3b, 0xf771768c, 0xfa325055, 0xfef34de2,
        0xc6bcf05f, 0xc27dede8, 0xcf3ecb31, 0xcbffd686,
        0xd5b88683, 0xd1799b34, 0xdc3abded, 0xd8fba05a,
        0x690ce0ee, 0x6dcdfd59, 0x608edb80, 0x644fc637,
        0x7a089632, 0x7ec98b85, 0x738aad5c, 0x774bb0eb,
        0x4f040d56, 0x4bc510e1, 0x46863638, 0x42472b8f,
        0x5c007b8a, 0x58c1663d, 0x558240e4, 0x51435d53,
        0x251d3b9e, 0x21dc2629, 0x2c9f00f0, 0x285e1d47,
        0x36194d42, 0x32d850f5, 0x3f9b762c, 0x3b5a6b9b,
        0x0315d626, 0x07d4cb91, 0x0a97ed48, 0x0e56f0ff,
        0x1011a0fa, 0x14d0bd4d, 0x19939b94, 0x1d528623,
        0xf12f560e, 0xf5ee4bb9, 0xf8ad6d60, 0xfc6c70d7,
        0xe22b20d2, 0xe6ea3d65, 0xeba91bbc, 0xef68060b,
        0xd727bbb6, 0xd3e6a601, 0xdea580d8, 0xda649d6f,
        0xc423cd6a, 0xc0e2d0dd, 0xcda1f604, 0xc960ebb3,
        0xbd3e8d7e, 0xb9ff90c9, 0xb4bcb610, 0xb07daba7,
        0xae3afba2, 0xaafbe615, 0xa7b8c0cc, 0xa379dd7b,
        0x9b3660c6, 0x9ff77d71, 0x92b45ba8, 0x9675461f,
        0x8832161a, 0x8cf30bad, 0x81b02d74, 0x857130c3,
        0x5d8a9099, 0x594b8d2e, 0x5408abf7, 0x50c9b640,
        0x4e8ee645, 0x4a4ffbf2, 0x470cdd2b, 0x43cdc09c,
        0x7b827d21, 0x7f436096, 0x7200464f, 0x76c15bf8,
        0x68860bfd, 0x6c47164a, 0x61043093, 0x65c52d24,
        0x119b4be9, 0x155a565e, 0x18197087, 0x1cd86d30,
        0x029f3d35, 0x065e2082, 0x0b1d065b, 0x0fdc1bec,
        0x3793a651, 0x3352bbe6, 0x3e119d3f, 0x3ad08088,
        0x2497d08d, 0x2056cd3a, 0x2d15ebe3, 0x29d4f654,
        0xc5a92679, 0xc1683bce, 0xcc2b1d17, 0xc8ea00a0,
        0xd6ad50a5, 0xd26c4d12, 0xdf2f6bcb, 0xdbee767c,
        0xe3a1cbc1, 0xe760d676, 0xea23f0af, 0xeee2ed18,
        0xf0a5bd1d, 0xf464a0aa, 0xf9278673, 0xfde69bc4,
        0x89b8fd09, 0x8d79e0be, 0x803ac667, 0x84fbdbd0,
        0x9abc8bd5, 0x9e7d9662, 0x933eb0bb, 0x97ffad0c,
        0xafb010b1, 0xab710d06, 0xa6322bdf, 0xa2f33668,
        0xbcb4666d, 0xb8757bda, 0xb5365d03, 0xb1f740b4]

def crc32(data):
    i_crc = 0xffffffff;
    for ch in data:
        i_crc = ((i_crc << 8) & 0xffffffff) ^ _CRC32[(i_crc >> 24) ^ ord(ch)]
    b0 = i_crc >> 24
    b1 = (i_crc & 0x00ff0000) >> 16
    b2 = (i_crc & 0x0000ff00) >> 8
    b3 = i_crc & 0xff
    return '%s%s%s%s' % (chr(b0), chr(b1), chr(b2), chr(b3))

if __name__=='__main__':
    index = 0
    ts = TsHandler()
    while True:
        index = index + 1
        f = '/Users/michael/Github/rtmp-livestreaming/tmp/ad/tags/%03d.tag' % index
        #f = '/Users/michael/Github/rtmp-livestreaming/tmp/flv/%05d.tag' % index
        if os.path.isfile(f):
            print 'Process tag %d ...' % index
            with open(f, 'r+b') as fp:
                tag = fp.read()
                ts.processTag(tag)
        else:
            break
    f = open('/Users/michael/Github/rtmp-livestreaming/tmp/ad/debug-extract-all.ts', 'w+b')
    f.write(ts._pat)
    f.write(ts._pmt)
    for tag in ts._tag_collector._tags:
        if tag.tag_type == _TAG_TYPE_AAC:
            ts._aacparser.writeTS(f, tag)
        if tag.tag_type == _TAG_TYPE_H264:
            ts._h264parser.writeTS(f, tag)
    f.close()
