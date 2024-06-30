using System;
using System.Collections.Generic;
using System.IO;
using System.Linq;
using SixLabors.ImageSharp;
using SixLabors.ImageSharp.PixelFormats;

class GrdMetaData
{
    public ushort Format { get; set; }
    public int Width { get; set; }
    public int Height { get; set; }
    public ushort BPP { get; set; }
    public int OffsetX { get; set; }
    public int OffsetY { get; set; }
    public uint AlphaSize { get; set; }
    public uint RSize { get; set; }
    public uint GSize { get; set; }
    public uint BSize { get; set; }
}

class GrdReader
{
    private BinaryReader _input;
    private GrdMetaData _info;
    public byte[] Output { get; private set; }
    private byte[] _channel;
    private byte _packType;
    private int _pixelSize;

    public GrdReader(BinaryReader input, GrdMetaData info)
    {
        _input = input;
        _info = info;
        Output = new byte[info.Width * info.Height * (info.BPP / 8)];
        _channel = new byte[info.Width * info.Height];
        _packType = (byte)(info.Format >> 8);
        _pixelSize = info.BPP / 8;
    }

    public void Unpack()
    {
        int nextPos = 0x20;
        if (_info.BPP == 32 && _info.AlphaSize > 0)
        {
            UnpackChannel(3, nextPos, (int)_info.AlphaSize);
            nextPos += (int)_info.AlphaSize;
        }
        UnpackChannel(0, nextPos, (int)_info.RSize);
        nextPos += (int)_info.RSize;
        UnpackChannel(1, nextPos, (int)_info.GSize);
        nextPos += (int)_info.GSize;
        UnpackChannel(2, nextPos, (int)_info.BSize);
    }

    private void UnpackChannel(int dst, int srcPos, int srcSize)
    {
        _input.BaseStream.Seek(srcPos, SeekOrigin.Begin);

        if (_packType == 1)
        {
            UnpackRle(_input, srcSize);
        }
        else
        {
            byte[] data = UnpackHuffman(_input);
            if (_packType == 0xA2)
            {
                UnpackLz77(data, _channel);
            }
            else
            {
                using (var ms = new MemoryStream(data))
                using (var br = new BinaryReader(ms))
                {
                    UnpackRle(br, data.Length);
                }
            }
        }

        for (int y = _info.Height - 1; y >= 0; y--)
        {
            int src = y * _info.Width;
            for (int x = 0; x < _info.Width; x++)
            {
                Output[dst] = _channel[src];
                src++;
                dst += _pixelSize;
            }
        }
    }

    private void UnpackRle(BinaryReader inputStream, int srcSize)
    {
        int src = 0;
        int dst = 0;
        while (src < srcSize)
        {
            byte count = inputStream.ReadByte();
            src++;
            if (count > 0x7F)
            {
                count &= 0x7F;
                byte v = inputStream.ReadByte();
                src++;
                for (int i = 0; i < count; i++)
                {
                    _channel[dst++] = v;
                }
            }
            else if (count > 0)
            {
                inputStream.Read(_channel, dst, count);
                src += count;
                dst += count;
            }
        }
    }

    private static void UnpackLz77(byte[] inputData, byte[] output)
    {
        byte special = inputData[8];
        int src = 12;
        int dst = 0;
        while (dst < output.Length)
        {
            byte b = inputData[src++];
            if (b == special)
            {
                byte offset = inputData[src++];
                if (offset != special)
                {
                    byte count = inputData[src++];
                    if (offset > special)
                    {
                        offset--;
                    }
                    for (int i = 0; i < count; i++)
                    {
                        output[dst] = output[dst - offset];
                        dst++;
                    }
                }
                else
                {
                    output[dst++] = offset;
                }
            }
            else
            {
                output[dst++] = b;
            }
        }
    }

    private byte[] UnpackHuffman(BinaryReader inputStream)
    {
        var tree = CreateHuffmanTree(inputStream);
        var unpacked = new byte[_huffmanUnpacked];
        var bits = new LsbBitStream(inputStream);
        int dst = 0;
        while (dst < _huffmanUnpacked)
        {
            int node = 0x1FE;
            while (node > 0xFF)
            {
                if (bits.GetNextBit() != 0)
                {
                    node = tree[node].Right;
                }
                else
                {
                    node = tree[node].Left;
                }
            }
            unpacked[dst++] = (byte)node;
        }
        return unpacked;
    }

    private int _huffmanUnpacked;

    private HuffmanNode[] CreateHuffmanTree(BinaryReader inputStream)
    {
        var nodes = new HuffmanNode[0x200];
        for (int i = 0; i < nodes.Length; i++)
        {
            nodes[i] = new HuffmanNode();
        }
        var tree = new List<int>();
        _huffmanUnpacked = inputStream.ReadInt32();
        inputStream.ReadInt32(); // packed_size

        for (int i = 0; i < 0x100; i++)
        {
            nodes[i].Freq = inputStream.ReadUInt32();
            AddNode(tree, nodes, i);
        }

        int lastNode = 0x100;
        while (tree.Count > 1)
        {
            int l = tree[0];
            tree.RemoveAt(0);
            int r = tree[0];
            tree.RemoveAt(0);
            nodes[lastNode].Freq = nodes[l].Freq + nodes[r].Freq;
            nodes[lastNode].Left = l;
            nodes[lastNode].Right = r;
            AddNode(tree, nodes, lastNode);
            lastNode++;
        }

        return nodes;
    }

    private static void AddNode(List<int> tree, HuffmanNode[] nodes, int index)
    {
        uint freq = nodes[index].Freq;
        for (int i = 0; i < tree.Count; i++)
        {
            if (nodes[tree[i]].Freq > freq)
            {
                tree.Insert(i, index);
                return;
            }
        }
        tree.Add(index);
    }
}

class HuffmanNode
{
    public uint Freq { get; set; }
    public int Left { get; set; }
    public int Right { get; set; }
}

class LsbBitStream
{
    private BinaryReader _stream;
    private byte _currentByte;
    private int _bitPosition;

    public LsbBitStream(BinaryReader stream)
    {
        _stream = stream;
        _currentByte = 0;
        _bitPosition = 8;
    }

    public int GetNextBit()
    {
        if (_bitPosition == 8)
        {
            _currentByte = _stream.ReadByte();
            _bitPosition = 0;
        }
        int bit = _currentByte & 1;
        _currentByte >>= 1;
        _bitPosition++;
        return bit;
    }
}