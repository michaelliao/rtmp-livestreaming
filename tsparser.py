#!/usr/bin/env python
# -*- coding: utf-8 -*-

_PROGRAM_STREAM_MAP = 0xbc
_PADDING_STREAM = 0xbe
_PRIVATE_STREAM_2 = 0xbf
_ECM = 0xf0
_EMM = 0xf1
_PROGRAM_STREAM_DIRECTORY = 0xff
_DSMCC_STREAM = 0xf2
_ITU_T_REC_H_222_1_TYPE_E_STREAM = 0xf8

class Packet(object):

    def __init__(self, data):
        self._data = data # 187 bytes data as str (no sync byte)
        self._position = 0

    def __getitem__(self, val):
        return self._data.__getitem__(val)

    def data(self):
        return self._data

    def read_byte(self):
        if self._position < 187:
            b = self._data[self._position]
            self._position = self._position + 1
            return ord(b)
        raise IOError('EOF of packet.')

    def read_int16(self):
        b1 = self.read_byte()
        b2 = self.read_byte()
        return (b1 << 8) + b2

    def read_int24(self):
        b1 = self.read_byte()
        b2 = self.read_byte()
        b3 = self.read_byte()
        return (b1 << 16) + (b2 << 8) + b3

    def read_int32(self):
        b1 = self.read_int16()
        b2 = self.read_int16()
        return (b1 << 16) + b2

    def skip(self, numberOfBytes):
        end = self._position + numberOfBytes
        if end > 187:
            raise IOError('Index out of bounds after skip %d bytes.' % numberOfBytes)
        self._position = end

    def position(self):
        return self._position

    def left(self):
        return self._data[self._position:]

    def eof(self):
        'return True if EOF, else false.'
        return self._position==187

def read_packet(fp):
    ' locate sync code 0x47 and return 187 bytes if available. '
    while True:
        b = fp.read(1)
        if b=='': # EOF
            print '# EOF #'
            return ''
        if b=='\x47':
            return fp.read(187)
        print 'WARNING: sync code not found!'

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

class PES(object):

    def __init__(self, length):
        self._length = length
        self._data = []

    def append(self, data):
        self._data.append(data)

    def data(self):
        d = ''.join(self._data)
        print 'INFO: PES length expected %d but actual %d (%d)!' % (self._length, len(d), len(d)-self._length)
        return d

class TsParser(object):

    def __init__(self):
        self._index = 0
        self._pat_data = None
        self._pmt_pid = None
        self._pmt_data = None
        self._video_pid = None
        self._audio_pid = None

        self._audio_pes_list = []
        self._video_pes_list = []

        self._audio_pes = None
        self._video_pes = None

    def parse(self, data):
        self._index = self._index + 1
        p = Packet(data)
        b1 = p.read_byte()
        b2 = p.read_byte()
        b3 = p.read_byte()
        pusi = (b1 & 0x4f) >> 6
        pid = ((b1 & 0x1f) << 8) | b2
        af = (b3 & 0x30) >> 4
        ccounter = b3 & 0x0f
        print '--------------------------------------------------------------------------------'
        print '#', self._index
        print 'pusi = %d, PID = %d, af = %d, cc = %d' % (pusi, pid, af, ccounter)
        if af & 0x2:
            af_length = p.read_byte()
            if af_length > 0:
                af_1 = p.read_byte()
                af_length = af_length - 1
                DI, RI, EI, PCR_F, OPCR_F, SF, TF, AF = (af_1 & 0x80) >> 7, (af_1 & 0x40) >>6, (af_1 & 0x20) >> 5, (af_1 & 0x10) >> 4, (af_1 & 0x8) >> 3, (af_1 & 0x4) >> 2, (af_1 & 0x2) >> 1, af_1 & 0x1
                # only RI, PCR_F can be 1:
                # random access indicator
                # PCR flag
                if PCR_F:
                    if af_length < 6:
                        raise StandardError('Bad TS packet!')
                    c32 = p.read_int32()
                    c4 = p.read_byte()
                    c5 = p.read_byte()
                    pcr_base = (c32 << 1) | ((c4 & 0x80) >> 7)
                    pcr_ext = ((c4 & 0x1) << 8) | c5
                    print 'PCR base / ext = %d, %d' % (pcr_base, pcr_ext)
                    af_length = af_length - 6
                if af_length>=0:
                    p.skip(af_length)
                else:
                    print 'ERROR: bad AF length.'
        if af & 0x01:
            # has payload:
            if pid==0:
                program_map_PID = self._parse_pat(p)
                if program_map_PID:
                    self._pmt_pid = program_map_PID
                    self._pat_data = p.data()
            elif pid==self._pmt_pid:
                self._video_pid, self._audio_pid = self._parse_pmt(p)
                self._pmt_data = p.data()
            elif pid==self._video_pid:
                self._parse_video(pusi, p)
            elif pid==self._audio_pid:
                self._parse_audio(pusi, p)
            else:
                print 'WARNING: cannot process pid:', pid

    def _parse_video(self, pusi, p):
        pts, dts, pes_packet_length, data = self._parse_pes(pusi, p, expected_stream_id=0xe0)
        if pusi:
            # start a new PES:
            if self._video_pes:
                self._video_pes_list.append(self._video_pes)
            self._video_pes = PES(pes_packet_length)
        if data and self._video_pes:
            self._video_pes.append(data)

    def _parse_audio(self, pusi, p):
        pts, dts, pes_packet_length, data = self._parse_pes(pusi, p, expected_stream_id=0xc0)
        if pusi:
            # start a new PES:
            if self._audio_pes:
                self._audio_pes_list.append(self._audio_pes)
            self._audio_pes = PES(pes_packet_length)
        if data and self._audio_pes:
            self._audio_pes.append(data)

    def _parse_pes(self, pusi, p, expected_stream_id):
        ' return pts, dts, data '
        pts = None
        dts = None
        pes_packet_length = 0
        if pusi:
            pes_start_code = p.read_int24()
            print 'Audio' if expected_stream_id==0xc0 else 'Video', 'PES start:'
            stream_id = p.read_byte()
            print '  stream_id:', stream_id
            if (stream_id & 0xe0) != expected_stream_id:
                print 'ERROR: NOT expected stream!'
            pes_packet_length = p.read_int16()
            print '  PES packet length:', pes_packet_length
            p.skip(1) # 0x80: ignore '10', PES_scrambling_control (2 bit), PES_priority (2 bit), data_alignment_indicator (1 bit), copyright (1 bit), original_or_copy (1 bit)
            b = p.read_byte() # 0x80 or 0xc0
            pts_dts_flag = (b & 0xc0) >> 6 # '10' or '11'
            escr_flag = (b & 0x20) >> 5
            es_rate_flag = (b & 0x10) >> 4
            dsm_trick_mode_flag = (b & 0x08) >> 3
            additional_copy_info_flag = (b & 0x04) >> 2
            pes_crc_flag = (b & 0x02) >> 1
            pes_extension_flag = b & 0x01

            pes_header_data_length = p.read_byte()
            print '  PES header data length:', pes_header_data_length
            pes_hdl_remaining = pes_header_data_length
            if pts_dts_flag==0x02:
                # '0010' PTS[32..30] '1' PTS[29..15] '1' PTS[14..0] '1'
                pts = ((p.read_byte() & 0x0e) << 29) + \
                      ((p.read_int16() & 0xfffe) << 14) + \
                      ((p.read_int16() & 0xfffe) >> 1)
                pes_hdl_remaining = pes_hdl_remaining - 5
                print '  PTS:', pts
            elif pts_dts_flag==0x03:
                # '0011' PTS[32..30] '1' PTS[29..15] '1' PTS[14..0] '1'
                pts = ((p.read_byte() & 0x0e) << 29) + \
                      ((p.read_int16() & 0xfffe) << 14) + \
                      ((p.read_int16() & 0xfffe) >> 1)
                # '0001' DTS[32..30] '1' DTS[29..15] '1' DTS[14..0] '1'
                dts = ((p.read_byte() & 0x0e) << 29) + \
                      ((p.read_int16() & 0xfffe) << 14) + \
                      ((p.read_int16() & 0xfffe) >> 1)
                pes_hdl_remaining = pes_hdl_remaining - 10
                print '  PTS:', pts, 'DTS:', dts
                print '  PTS - DTS', (pts - dts)
            if escr_flag:
                p.skip(6) # 48 bit
                pes_hdl_remaining = pes_hdl_remaining - 6
            if es_rate_flag:
                p.skip(3) # 24 bit
                pes_hdl_remaining = pes_hdl_remaining - 3
            if dsm_trick_mode_flag:
                p.skip(1) # trick_mode_control (3 bit) + 5 bit
                pes_hdl_remaining = pes_hdl_remaining - 1
            if additional_copy_info_flag:
                p.skip(1) # 8 bit
                pes_hdl_remaining = pes_hdl_remaining - 1
            if pes_crc_flag:
                p.skip(2) # 16 bit
                pes_hdl_remaining = pes_hdl_remaining - 2
            if pes_extension_flag:
                b = p.read_byte()
                pes_hdl_remaining = pes_hdl_remaining - 1

                pes_private_data_flag = (b & 0x80) >> 7
                pack_header_field_flag = (b & 0x40) >> 6
                program_packet_sequence_counter_flag = (b & 0x20) >> 5
                p_std_buffer_flag = (b & 0x10) >> 4
                # reserved 3 bit
                pes_extension_flag_2 = (b & 0x01)
                if pes_private_data_flag:
                    p.skip(16) # 128 bit
                    pes_hdl_remaining = pes_hdl_remaining - 16
                if pack_header_field_flag:
                    pack_header_length = p.read_byte()
                    p.skip(pack_header_length)
                    pes_hdl_remaining = pes_hdl_remaining - pack_header_length
                if program_packet_sequence_counter_flag:
                    p.skip(2) # 16 bit
                    pes_hdl_remaining = pes_hdl_remaining - 2
                if p_std_buffer_flag:
                    p.skip(2) # 16 bit
                    pes_hdl_remaining = pes_hdl_remaining - 2
                if pes_extension_flag_2:
                    pes_extension_field_length = p.read_byte() & 0x7f
                    p.skip(pes_extension_field_length)
                    pes_hdl_remaining = pes_hdl_remaining - pes_extension_field_length
            if pes_hdl_remaining>=0:
                p.skip(pes_hdl_remaining)
            else:
                print 'ERROR: bad PES header data length!'
            pes_packet_length = pes_packet_length - pes_header_data_length - 3
        return pts, dts, pes_packet_length, p.left()

    def flush(self):
        if self._audio_pes:
            self._audio_pes_list.append(self._audio_pes)
        self._audio_pes = None
        if self._video_pes:
            self._video_pes_list.append(self._video_pes)
        self._video_pes = None

    def _parse_pat(self, p):
        print 'try parse PAT...'
        # skip pointer = 0x00, tableID = 0x00:
        p.skip(2)
        # read section_length (including CRC32):
        #   section_syntax_indicator = 1 (1 bit),
        #   '0' (1 bit)
        #   reserved 00 (2 bit)
        #   section_length (12 bit)
        section_length = ((p.read_byte() & 0x0f) << 8) + p.read_byte()
        transport_tream_id = p.read_int16()
        current_next_indicator = p.read_byte() & 0x01
        section_number = p.read_byte()
        last_section_number = p.read_byte()
        for i in range(section_number, last_section_number + 1):
            program_number = p.read_int16()
            program_map_PID = p.read_int16() & 0x1fff # last 13 bit
            print 'program number / pmtPID =', program_number, program_map_PID
            return program_map_PID
        # ignore CRC32 and rest 0xff...
        return None

    def _parse_pmt(self, p):
        print 'try parse PMT...'
        # pointer = 0x00, tableID = 0x02:
        pointer = p.read_byte()
        if p.read_byte() != 0x02:
            print 'WARNING: table id not 0x02 when parse PMT.'
            return None
        section_length = ((p.read_byte() & 0x0f) << 8) + p.read_byte()
        # skip program num, rserved, version, cni, section num, last section num, reserved, PCR PID
        p.skip(7)
        program_info_length = p.read_int16() & 0x0fff # 12 bit
        p.skip(program_info_length)
        remaining = section_length - program_info_length - 9
        video_pid = None
        audio_pid = None
        while remaining > 4:
            t = p.read_byte()
            pid = p.read_int16() & 0x1fff
            es_info_length = p.read_int16() & 0x0fff
            p.skip(es_info_length)
            remaining = remaining - es_info_length - 5
            if t==0x1b:
                # H.264 video:
                video_pid = pid
            elif t==0x0f:
                # AAC audio:
                audio_pid = pid
            else:
                print 'WARNING: CANNOT process type:', t
        print 'Video, audio pid:',video_pid, audio_pid
        return video_pid, audio_pid

if __name__=='__main__':
    fp = open('/Users/michael/Github/rtmp-livestreaming/tmp/ad/m.ts', 'rb')
    parser = TsParser()
    n = 0
    while True:
        s = read_packet(fp)
        if s:
            parser.parse(s)
        else:
            break
        n = n + 1
    fp.close()
    parser.flush()
