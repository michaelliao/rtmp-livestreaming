#!/usr/bin/env python
# -*- coding: utf-8 -*-

' parse flv tags'

import struct

FLV_SOUND_FORMAT_AAC = 10 # AAC

FLV_VIDEO_FORMAT_AVC = 7 # H.264

FLV_KEY_FRAME = 1 # key frame (for AVC, a seekable frame)
# 2 = inter frame (for AVC, a non-seekable frame)
# 3 = disposable inter frame (H.263 only)
# 4 = generated key frame (reserved for server use only)
# 5 = video info/command frame

class FLVError(StandardError):
    pass

_MASKS = (0x80, 0x40, 0x20, 0x10, 0x08, 0x04, 0x02, 0x01)

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

# AAC ADTS Header 7 bytes
# syncword, ID, layer, protection_absent
# | ssss ssss | ssss illp |
# profile, sampling, private_bit, channel_conf original_copy, home, copyright_id_bit, copy_start,
# aac_frame_length, buffer_fullness, number_of_raw_data_blocks
# | ppss sspc ccoh ccll llll llll lllb bbbb bbbb bbnn |

class AACParser(object):
    def __init__(self, output):
        self._adts_header = None
        self._output = output

    def parse(self, s):
        print '------------------------------------------------------------'
        length = s.read_uint24()
        print 'length:', length
        timestamp = s.read_uint24()
        print 'timestamp:', timestamp
        extend_ts = s.read_uint8()
        print 'extend_timestamp:', extend_ts
        stream_id = s.read_uint24()
        print 'stream_id (always 0):', stream_id
        b = s.read_uint8()
        if ((b & 0xf0) >> 4) != FLV_SOUND_FORMAT_AAC:
            raise FLVError('Bad audio format: not AAC.')
        sound_rate = (b & 0x0c) >> 2
        print 'sound rate (0-3, 5.5, 11, 22, 44):', sound_rate
        sound_sample = (b & 0x02) >> 1
        print 'sound sample (0=8, 1=16):', sound_sample
        sound_type = b & 0x01
        print 'sound type (0=mono,1=stereo):', sound_type
        # AACPacketType:
        if s.read_uint8()==0:
            print 'AAC sequence header:'
            self._parse_aac_sequence(s)
        else:
            print 'AAC RAW'
            if self._adts_header:
                self._parse_aac_raw(s)
            else:
                print 'ERROR: no adts header but meet raw!'

    def _parse_aac_raw(self, s):
        payload = s.left()
        print 'raw length:', len(payload)
        # aac frame size = ADTS_HEADER_SIZE (7 bytes) + payload size
        size = 7 + len(payload)
        # 13 bits size:
        c3, c5 = ord(self._adts_header[3]), ord(self._adts_header[5])
        i3 = ((size & 0x1800) >> 11) | (c3 & 0xfc)
        i4 = (size & 0x07f8) >> 3
        i5 = ((size & 0x07) << 5) | (c5 & 0x1f)
        self._output.write(self._adts_header[0:3])
        self._output.write(chr(i3))
        self._output.write(chr(i4))
        self._output.write(chr(i5))
        self._output.write(self._adts_header[6])
        self._output.write(payload)

    def _parse_aac_sequence(self, s):
        print '[FRAME]'
        b1 = s.read_uint8()
        b2 = s.read_uint8()
        aac_object_type = (b1 & 0xf8) >> 3
        print 'aac_object_type (0=main, 1=lc, 2=ssr, 3=LTP):', aac_object_type
        # fix to 01:
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
        self._adts_header = pb.value()

class H264Parser(object):

    def __init__(self, output):
        self._output = output
        self._nalu_length_size = 0

    def parse(self, s):
        print '------------------------------------------------------------'
        length = s.read_uint24()
        print 'length:', length
        timestamp = s.read_uint24()
        print 'timestamp:', timestamp
        extend_ts = s.read_uint8()
        print 'extend_timestamp:', extend_ts
        stream_id = s.read_uint24()
        videoTagHeader = s.read_uint8()
        if (videoTagHeader & 0x0f) != FLV_VIDEO_FORMAT_AVC:
            raise FLVError('Bad video format: not H264.')
        frameType = (videoTagHeader & 0xf0) >> 4
        print 'Frame type (1=I, 2=P):', frameType
        AVCPacketType = s.read_uint8()
        print 'avc packet type (0=seq header, 1=NALU, 2=end seq):', AVCPacketType
        compositionTime = s.read_uint24()
        print 'composition time (in ms):', compositionTime
        if AVCPacketType==0:
            # See ISO 14496-15, 5.2.4.1 for the description of AVCDecoderConfigurationRecord.
            # This contains the same information that would be stored in an avcC box in an MP4/FLV file.
            self._parse_config_record(s)
        elif AVCPacketType==1:
            # One or more NALUs (Full frames are required)
            self._parse_NALUs(s)
        else:
            raise FLVError('Bad AVCPacketType: %d' % AVCPacketType)

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
            print 'spsNALU:', spsNALU
        num_of_pps = s.read_uint8()
        print 'num_of_pps:', num_of_pps
        for i in range(num_of_pps):
            pps_length = s.read_uint16()
            ppsNALU = s.read_bytes(pps_length)
            print 'ppsNALU:', ppsNALU
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
        print 'NALU length:', length
        print 'data available:', s.available()


if __name__=='__main__':
    aac_fp = open('/Users/michael/Github/rtmp-livestreaming/generated.aac', 'wb')
    h264_fp = open('/Users/michael/Github/rtmp-livestreaming/generated.h264', 'wb')
    aac = AACParser(aac_fp)
    h264 = H264Parser(h264_fp)
    for i in range(47):
        f = '/Users/michael/Github/rtmp-livestreaming/tmp/flvdebug-%d' % i
        fp = open(f, 'rb')
        s = BytesIO(fp.read())
        fp.close()
        tag_type = s.read_uint8() & 0x1f
        if tag_type==8:
            pass #aac.parse(s)
        elif tag_type==9:
            print '#', i,
            h264.parse(s)
    aac_fp.close()
    h264_fp.close()

    import doctest
    doctest.testmod()
