#!/usr/bin/env python
# -*- coding: utf-8 -*-

'''
Generate a sequence of filename with a given seed.
'''

from hashlib import md5

SS = '0123456789ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghijklmnopqrstuvwxyz-_'

def seq_generator(seed='DEFAULT'):
    n = 0
    init = md5(str(seed))
    while True:
        n = n + 1
        b0 = (n & 0xfc0000) >> 18
        b1 = (n & 0x3f000) >> 12
        b2 = (n & 0xfc0) >> 6
        b3 = (n & 0x3f)
        d = init.digest()
        d0, d1, d2, d3 = ord(d[0]) & 0x3f, ord(d[1]) & 0x3f, ord(d[2]) & 0x3f, ord(d[3]) & 0x3f
        h = '%s%s%s%s%s%s%s%s' % (SS[b0], SS[b1], SS[b2], SS[b3], SS[d0], SS[d1], SS[d2], SS[d3])
        yield h
        init.update(d[:n & 0xf])

if __name__=='__main__':
    seq = seq_generator('test')
    for i in range(100):
        print seq.next()
