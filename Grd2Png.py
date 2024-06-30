import argparse
import os
import struct
from PIL import Image
import io

class GrdMetaData:
    def __init__(self):
        self.Format = 0
        self.Width = 0
        self.Height = 0
        self.BPP = 0
        self.OffsetX = 0
        self.OffsetY = 0
        self.AlphaSize = 0
        self.RSize = 0
        self.GSize = 0
        self.BSize = 0

class GrdReader:
    def __init__(self, input_stream, info):
        self.input = input_stream
        self.info = info
        self.output = bytearray(info.Width * info.Height * (info.BPP // 8))
        self.channel = bytearray(info.Width * info.Height)
        self.pack_type = info.Format >> 8
        self.pixel_size = info.BPP // 8

    def unpack(self):
        next_pos = 0x20
        if self.info.BPP == 32 and self.info.AlphaSize > 0:
            self.unpack_channel(3, next_pos, self.info.AlphaSize)
            next_pos += self.info.AlphaSize
        self.unpack_channel(0, next_pos, self.info.RSize)  # Red channel
        next_pos += self.info.RSize
        self.unpack_channel(1, next_pos, self.info.GSize)  # Green channel
        next_pos += self.info.GSize
        self.unpack_channel(2, next_pos, self.info.BSize)  # Blue channel

    def unpack_channel(self, dst, src_pos, src_size):
        self.input.seek(src_pos)

        if self.pack_type == 1:
            self.unpack_rle(self.input, src_size)
        else:
            data = self.unpack_huffman(self.input)
            if self.pack_type == 0xA2:
                self.unpack_lz77(data, self.channel)
            else:
                self.unpack_rle(io.BytesIO(data), len(data))

        for y in range(self.info.Height - 1, -1, -1):
            src = y * self.info.Width
            for x in range(self.info.Width):
                self.output[dst] = self.channel[src]
                src += 1
                dst += self.pixel_size

    def unpack_rle(self, input_stream, src_size):
        src = 0
        dst = 0
        while src < src_size:
            count = input_stream.read(1)[0]
            src += 1
            if count > 0x7F:
                count &= 0x7F
                v = input_stream.read(1)[0]
                src += 1
                self.channel[dst:dst+count] = [v] * count
                dst += count
            elif count > 0:
                self.channel[dst:dst+count] = input_stream.read(count)
                src += count
                dst += count

    @staticmethod
    def unpack_lz77(input_data, output):
        special = input_data[8]
        src = 12
        dst = 0
        while dst < len(output):
            b = input_data[src]
            src += 1
            if b == special:
                offset = input_data[src]
                src += 1
                if offset != special:
                    count = input_data[src]
                    src += 1
                    if offset > special:
                        offset -= 1
                    for i in range(count):
                        output[dst] = output[dst - offset]
                        dst += 1
                else:
                    output[dst] = offset
                    dst += 1
            else:
                output[dst] = b
                dst += 1

    def unpack_huffman(self, input_stream):
        tree = self.create_huffman_tree(input_stream)
        unpacked = bytearray(self.huffman_unpacked)
        bits = LsbBitStream(input_stream)
        dst = 0
        while dst < self.huffman_unpacked:
            node = 0x1FE
            while node > 0xFF:
                if bits.get_next_bit() != 0:
                    node = tree[node].right
                else:
                    node = tree[node].left
            unpacked[dst] = node
            dst += 1
        return unpacked

    def create_huffman_tree(self, input_stream):
        nodes = [HuffmanNode() for _ in range(0x200)]
        tree = []
        self.huffman_unpacked = struct.unpack('<I', input_stream.read(4))[0]
        input_stream.read(4)  # packed_size

        for i in range(0x100):
            nodes[i].freq = struct.unpack('<I', input_stream.read(4))[0]
            self.add_node(tree, nodes, i)

        last_node = 0x100
        while len(tree) > 1:
            l = tree.pop(0)
            r = tree.pop(0)
            nodes[last_node].freq = nodes[l].freq + nodes[r].freq
            nodes[last_node].left = l
            nodes[last_node].right = r
            self.add_node(tree, nodes, last_node)
            last_node += 1

        return nodes

    @staticmethod
    def add_node(tree, nodes, index):
        freq = nodes[index].freq
        for i, node in enumerate(tree):
            if nodes[node].freq > freq:
                tree.insert(i, index)
                return
        tree.append(index)

class HuffmanNode:
    def __init__(self):
        self.freq = 0
        self.left = 0
        self.right = 0

class LsbBitStream:
    def __init__(self, stream):
        self.stream = stream
        self.current_byte = 0
        self.bit_position = 8

    def get_next_bit(self):
        if self.bit_position == 8:
            self.current_byte = self.stream.read(1)[0]
            self.bit_position = 0
        bit = self.current_byte & 1
        self.current_byte >>= 1
        self.bit_position += 1
        return bit

def read_grd_metadata(file_path):
    with open(file_path, 'rb') as f:
        header = f.read(0x20)
        if header[0] not in (1, 2) or header[1] not in (1, 0xA1, 0xA2):
            return None
        bpp = struct.unpack('<H', header[6:8])[0]
        if bpp not in (24, 32):
            return None

        screen_width, screen_height = struct.unpack('<HH', header[2:6])
        left, right, top, bottom = struct.unpack('<HHHH', header[8:16])

        info = GrdMetaData()
        info.Format = struct.unpack('<H', header[:2])[0]
        info.Width = abs(right - left)
        info.Height = abs(bottom - top)
        info.BPP = bpp
        info.OffsetX = left
        info.OffsetY = screen_height - bottom
        info.AlphaSize, info.RSize, info.GSize, info.BSize = struct.unpack('<IIII', header[0x10:0x20])

        file_size = os.path.getsize(file_path)
        if 0x20 + info.AlphaSize + info.RSize + info.BSize + info.GSize != file_size:
            return None

        return info

def convert_grd_to_png(input_path, output_path):
    info = read_grd_metadata(input_path)
    if info is None:
        print(f"Invalid GRD file: {input_path}")
        return

    with open(input_path, 'rb') as f:
        reader = GrdReader(f, info)
        reader.unpack()

    if info.BPP == 24:
        mode = 'RGB'
    elif info.AlphaSize > 0:
        mode = 'RGBA'
    else:
        mode = 'RGB'

    image = Image.frombytes(mode, (info.Width, info.Height), bytes(reader.output))
    image.save(output_path, 'PNG')

def process_directory(input_dir, output_dir):
    if not os.path.exists(output_dir):
        os.makedirs(output_dir)

    for root, _, files in os.walk(input_dir):
        for file in files:
            if file.lower().endswith('.grd'):
                input_path = os.path.join(root, file)
                relative_path = os.path.relpath(input_path, input_dir)
                output_path = os.path.join(output_dir, os.path.splitext(relative_path)[0] + '.png')
                os.makedirs(os.path.dirname(output_path), exist_ok=True)
                convert_grd_to_png(input_path, output_path)
                print(f"Converted: {input_path} -> {output_path}")

def main():
    parser = argparse.ArgumentParser(description="Convert GRD files to PNG")
    parser.add_argument("input", help="Input GRD file or directory")
    parser.add_argument("output", help="Output PNG file or directory")
    args = parser.parse_args()

    if os.path.isdir(args.input):
        process_directory(args.input, args.output)
    else:
        convert_grd_to_png(args.input, args.output)

if __name__ == "__main__":
    main()
