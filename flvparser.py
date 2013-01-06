#!/usr/bin/env python
# -*- coding: utf-8 -*-

' parse flv tags'

import struct

# Format of SoundData. The following values are defined:
AUDIO_FORMAT_PCM    = 0 # Linear PCM, platform endian
AUDIO_FORMAT_ADPCM  = 1 # ADPCM
AUDIO_FORMAT_MP3    = 2 # MP3
AUDIO_FORMAT_LPCM   = 3 # Linear PCM, little endian
AUDIO_FORMAT_NEL16  = 4 # Nellymoser 16 kHz mono
AUDIO_FORMAT_NEL8   = 5 # Nellymoser 8 kHz mono
AUDIO_FORMAT_NEL    = 6 # Nellymoser
AUDIO_FORMAT_LG711  = 7 # G.711 A-law logarithmic PCM
AUDIO_FORMAT_MG711  = 8 # G.711 mu-law logarithmic PCM
AUDIO_FORMAT_R9     = 9 # reserved
AUDIO_FORMAT_AAC    = 10 # AAC
AUDIO_FORMAT_SPEEX  = 11 # Speex
AUDIO_FORMAT_MP3_8  = 14 # MP3 8 kHz
AUDIO_FORMAT_DEVICE = 15 # Device-specific sound
# Formats 7, 8, 14, and 15 are reserved.

AUDIO_RATE_5  = 0 # 5.5 kHz
AUDIO_RATE_11 = 1 # 11 kHz
AUDIO_RATE_22 = 2 # 22 kHz
AUDIO_RATE_44 = 3 # 44 kHz

AUDIO_SAMPLE_8  = 0 # 8-bit samples
AUDIO_SAMPLE_16 = 1 # 16-bit samples

AUDIO_TYPE_MONO   = 0 # Mono sound
AUDIO_TYPE_STEREO = 1 # Stereo sound

class FLVError(StandardError):
    pass

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

    def available(self):
        return self._length - self._position

    def skip(self, n):
        if self._position + n > self._length:
            raise IOError('Skip n bytes cause EOF.')
        self._position = self._position + n

def parse_audio_header(s):
    length = s.read_uint24()
    print 'length', length
    timestamp = s.read_uint24()
    print 'timestamp', timestamp
    extend_ts = s.read_uint8()
    print 'extend_ts', extend_ts
    stream_id = s.read_uint24()
    print 'stream_id', stream_id
    b = s.read_uint8()
    audio_format = (b & 0xf0) >> 4
    if audio_format!=AUDIO_FORMAT_AAC:
        raise FLVError('Bad audio format: not AAC.')
    audio_rate = (b & 0x0c) >> 2
    print 'audio_rate', audio_rate
    audio_sample = (b & 0x02) >> 1
    print 'audio sample', audio_sample
    audio_type = b & 0x01
    print 'audio type', audio_type
    if s.read_uint8()==0:
        print 'AAC sequence header'
    else:
        print 'AAC raw'

if __name__=='__main__':
    s = BytesIO('\x08\x00\x00\x04\x00\x00\x00\x00\x00\x00\x00\xaf\x00\x13\x88')
    print 'tag type', s.read_uint8()
    parse_audio_header(s)



