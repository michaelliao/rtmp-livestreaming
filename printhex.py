#!/usr/bin/env python
# -*- coding: utf-8 -*-

import sys

_MASKS = (0x80, 0x40, 0x20, 0x10, 0x08, 0x04, 0x02, 0x01)

def to_b(h):
    v = int(h, base=16)
    bits = ''
    for mask in _MASKS:
        if mask & v:
            bits = bits + '1'
        else:
            bits = bits + '0'
    return bits

def format_hex(h):
    if len(h)>2:
        raise ValueError('Bad format of hex value: %s' % h)
    if len(h)==1:
        return '0' + h
    return h

def print_l(line):
    s1 = ''
    s2 = ''
    for h in line:
        x = format_hex(h)
        s = '%s=%d,%d' % (x, int(x[0], base=16), int(x[1], base=16))
        while len(s)<9:
            s = s + ' '
        s1 = s1 + s
        s2 = s2 + to_b(x) + ' '
    print s1
    print s2

def print_b(*args):
    L = []
    line = []
    for arg in args:
        if len(line)==8:
            L.append(line)
            line = []
        line.append(arg)
    if len(line)>0:
        L.append(line)
    for l in L:
        print_l(l)

argv = sys.argv[1:]
if argv:
    print_b(*argv)
else:
    print 'Usage: hex.py 0f 2a 39 ff d0 ...'

