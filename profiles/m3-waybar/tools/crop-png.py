#!/usr/bin/env python3
"""裁 PNG 的一段并可选放大，输出新 PNG。用于验证截图（不进入配置）。"""
import struct, sys, zlib

def load(path):
    d = open(path,'rb').read(); pos=8; idat=b''
    while pos < len(d):
        ln = struct.unpack('>I', d[pos:pos+4])[0]
        typ = d[pos+4:pos+8]; data = d[pos+8:pos+8+ln]
        if typ==b'IHDR': W,H,depth,color = struct.unpack('>IIBB', data[:10])
        elif typ==b'IDAT': idat += data
        elif typ==b'IEND': break
        pos += 12+ln
    raw = zlib.decompress(idat)
    ch = {0:1,2:3,4:2,6:4}[color]; stride = W*ch
    prev = bytearray(stride); rows=[]
    def paeth(a,b,c):
        p=a+b-c; pa,pb,pc=abs(p-a),abs(p-b),abs(p-c)
        return a if pa<=pb and pa<=pc else (b if pb<=pc else c)
    i=0
    for _ in range(H):
        f=raw[i]; i+=1
        line=bytearray(raw[i:i+stride]); i+=stride
        if f==1:
            for x in range(ch,stride): line[x]=(line[x]+line[x-ch])&255
        elif f==2:
            for x in range(stride): line[x]=(line[x]+prev[x])&255
        elif f==3:
            for x in range(stride):
                a=line[x-ch] if x>=ch else 0
                line[x]=(line[x]+((a+prev[x])>>1))&255
        elif f==4:
            for x in range(stride):
                a=line[x-ch] if x>=ch else 0
                c=prev[x-ch] if x>=ch else 0
                line[x]=(line[x]+paeth(a,prev[x],c))&255
        rows.append(bytes(line)); prev=line
    return W,H,ch,rows

def save(path,W,H,rows):
    raw=b''.join(b'\x00'+r for r in rows)
    def chunk(t,d):
        c=t+d
        return struct.pack('>I',len(d))+c+struct.pack('>I',zlib.crc32(c)&0xffffffff)
    png=b'\x89PNG\r\n\x1a\n'
    png+=chunk(b'IHDR',struct.pack('>IIBBBBB',W,H,8,2,0,0,0))
    png+=chunk(b'IDAT',zlib.compress(raw,6))+chunk(b'IEND',b'')
    open(path,'wb').write(png)

src,dst,x0,y0,x1,y1,scale = sys.argv[1],sys.argv[2],*map(int,sys.argv[3:8])
W,H,ch,rows = load(src)
x0=max(0,x0); y0=max(0,y0); x1=min(W,x1); y1=min(H,y1)
out=[]
for y in range(y0,y1):
    line=rows[y]; row=bytearray()
    for x in range(x0,x1):
        o=x*ch; row += bytes((line[o],line[o+1],line[o+2]))
    for _ in range(scale):
        rr=bytearray()
        for x in range(x1-x0):
            o=x*3
            for _ in range(scale): rr += row[o:o+3]
        out.append(bytes(rr))
save(dst,(x1-x0)*scale,(y1-y0)*scale,out)
print(f'{dst}  {(x1-x0)*scale}x{(y1-y0)*scale}')
