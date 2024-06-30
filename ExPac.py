import os
import sys
import struct
from typing import List, Optional

class Entry:
    def __init__(self):
        self.name: str = ""
        self.offset: int = 0
        self.size: int = 0
        self.type: str = ""

    def check_placement(self, max_offset: int) -> bool:
        return self.offset + self.size <= max_offset

class ArcView:
    def __init__(self, file_path: str):
        self.file = open(file_path, "rb")
        self.max_offset = os.path.getsize(file_path)

    def read_int16(self, offset: int) -> int:
        self.file.seek(offset)
        return struct.unpack("<h", self.file.read(2))[0]

    def read_byte(self, offset: int) -> int:
        self.file.seek(offset)
        return struct.unpack("<B", self.file.read(1))[0]

    def read_uint32(self, offset: int) -> int:
        self.file.seek(offset)
        return struct.unpack("<I", self.file.read(4))[0]

    def read_int64(self, offset: int) -> int:
        self.file.seek(offset)
        return struct.unpack("<q", self.file.read(8))[0]

    def read_string(self, offset: int, length: int) -> str:
        self.file.seek(offset)
        return self.file.read(length).decode('utf-8').rstrip('\x00')

    def read_bytes(self, offset: int, size: int) -> bytes:
        self.file.seek(offset)
        return self.file.read(size)

def is_sane_count(count: int) -> bool:
    return 0 < count < 0x10000

def try_open(file_path: str) -> Optional[List[Entry]]:
    view = ArcView(file_path)
    count = view.read_int16(0)
    if not is_sane_count(count):
        return None
    name_length = view.read_byte(2)
    if name_length == 0:
        return None
    data_offset = view.read_uint32(3)
    if data_offset >= view.max_offset:
        return None

    index_size = 7 + (name_length + 8) * count
    if data_offset == index_size:
        version = 1
    elif data_offset == index_size + 4 * count:
        version = 2
    else:
        return None

    dir_entries = []
    index_offset = 7
    for i in range(count):
        name = view.read_string(index_offset, name_length)
        index_offset += name_length
        entry = Entry()
        entry.name = name
        if version == 1:
            entry.offset = view.read_uint32(index_offset) + data_offset
            entry.size = view.read_uint32(index_offset + 4)
            index_offset += 8
        else:
            entry.offset = view.read_int64(index_offset) + data_offset
            entry.size = view.read_uint32(index_offset + 8)
            index_offset += 12
        if not entry.check_placement(view.max_offset):
            return None
        dir_entries.append(entry)

    arc_name = os.path.splitext(os.path.basename(file_path))[0].lower()
    for entry in dir_entries:
        signature = view.read_uint32(entry.offset)
        if signature == 0x5367674F:  # 'OggS'
            entry.name = os.path.splitext(entry.name)[0] + ".ogg"
            entry.type = "audio"
        elif ((signature & 0xFF) == 1 or (signature & 0xFF) == 2) and "grd" in arc_name:
            entry.name = os.path.splitext(entry.name)[0] + ".grd"
            entry.type = "image"
        elif (signature & 0xFF) == 0x44 and entry.size - 9 == view.read_uint32(entry.offset + 5):
            entry.type = "audio"
        elif view.read_int16(entry.offset + 4) == 6 and view.read_uint32(entry.offset + 6) == 0x140050:
            entry.type = "script"
            if arc_name == "srp":
                entry.name = os.path.splitext(entry.name)[0] + ".srp"

    return dir_entries

def open_entry(view: ArcView, entry: Entry) -> bytes:
    if entry.type != "script" or view.read_int16(entry.offset + 4) != 6 or view.read_uint32(entry.offset + 6) != 0x140050:
        return view.read_bytes(entry.offset, entry.size)

    record_count = view.read_uint32(entry.offset)
    data = bytearray(view.read_bytes(entry.offset, entry.size))
    pos = 4
    for i in range(record_count):
        if pos + 2 > len(data):
            break
        chunk_size = struct.unpack("<H", data[pos:pos+2])[0] - 4
        pos += 6
        if pos + chunk_size > len(data):
            return data
        for j in range(chunk_size):
            data[pos] = (data[pos] >> 4) | ((data[pos] & 0x0F) << 4)
            pos += 1
    return data

def main():
    if len(sys.argv) != 3:
        print("Usage: python script.py input.pac output_directory")
        sys.exit(1)

    input_file = sys.argv[1]
    output_dir = sys.argv[2]

    if not input_file.lower().endswith('.pac'):
        print("Input file must be a .pac file")
        sys.exit(1)

    if not os.path.exists(output_dir):
        os.makedirs(output_dir)

    entries = try_open(input_file)
    if entries is None:
        print("Failed to open the PAC file")
        sys.exit(1)

    view = ArcView(input_file)
    for entry in entries:
        output_path = os.path.join(output_dir, entry.name)
        with open(output_path, 'wb') as out_file:
            data = open_entry(view, entry)
            out_file.write(data)
        print(f"Extracted: {entry.name}")

    print("Extraction complete")

if __name__ == "__main__":
    main()
