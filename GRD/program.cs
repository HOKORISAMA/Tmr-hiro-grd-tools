using System;
using System.IO;
using SixLabors.ImageSharp;
using SixLabors.ImageSharp.PixelFormats;
using SixLabors.ImageSharp.Processing;

class Program
{
    static GrdMetaData ReadGrdMetadata(string filePath)
    {
        using (var fileStream = File.OpenRead(filePath))
        using (var reader = new BinaryReader(fileStream))
        {
            byte[] header = reader.ReadBytes(0x20);
            if ((header[0] != 1 && header[0] != 2) || (header[1] != 1 && header[1] != 0xA1 && header[1] != 0xA2))
            {
                return null;
            }

            ushort bpp = BitConverter.ToUInt16(header, 6);
            if (bpp != 24 && bpp != 32)
            {
                return null;
            }

            ushort screenWidth = BitConverter.ToUInt16(header, 2);
            ushort screenHeight = BitConverter.ToUInt16(header, 4);
            ushort left = BitConverter.ToUInt16(header, 8);
            ushort right = BitConverter.ToUInt16(header, 10);
            ushort top = BitConverter.ToUInt16(header, 12);
            ushort bottom = BitConverter.ToUInt16(header, 14);

            var info = new GrdMetaData
            {
                Format = BitConverter.ToUInt16(header, 0),
                Width = Math.Abs(right - left),
                Height = Math.Abs(bottom - top),
                BPP = bpp,
                OffsetX = left,
                OffsetY = screenHeight - bottom,
                AlphaSize = BitConverter.ToUInt32(header, 0x10),
                RSize = BitConverter.ToUInt32(header, 0x14),
                GSize = BitConverter.ToUInt32(header, 0x18),
                BSize = BitConverter.ToUInt32(header, 0x1C)
            };

            long fileSize = new FileInfo(filePath).Length;
            if (0x20 + info.AlphaSize + info.RSize + info.BSize + info.GSize != fileSize)
            {
                return null;
            }

            return info;
        }
    }

    static void ConvertGrdToPng(string inputPath, string outputPath)
    {
        var info = ReadGrdMetadata(inputPath);
        if (info == null)
        {
            Console.WriteLine($"Invalid GRD file: {inputPath}");
            return;
        }

        using (var fileStream = File.OpenRead(inputPath))
        using (var reader = new BinaryReader(fileStream))
        {
            var grdReader = new GrdReader(reader, info);
            grdReader.Unpack();

            if (info.BPP == 24)
            {
                using (var image = Image.LoadPixelData<Rgb24>(grdReader.Output, info.Width, info.Height))
                {
                    image.Save(outputPath);
                }
            }
            else if (info.AlphaSize > 0)
            {
                using (var image = Image.LoadPixelData<Rgba32>(grdReader.Output, info.Width, info.Height))
                {
                    image.Save(outputPath);
                }
            }
            else
            {
                using (var image = Image.LoadPixelData<Rgb24>(grdReader.Output, info.Width, info.Height))
                {
                    image.Save(outputPath);
                }
            }
        }
    }

    static void ProcessDirectory(string inputDir, string outputDir)
    {
        if (!Directory.Exists(outputDir))
        {
            Directory.CreateDirectory(outputDir);
        }

        foreach (var filePath in Directory.EnumerateFiles(inputDir, "*.grd", SearchOption.AllDirectories))
        {
            string relativePath = Path.GetRelativePath(inputDir, filePath);
            string outputPath = Path.Combine(outputDir, Path.ChangeExtension(relativePath, ".png"));
            Directory.CreateDirectory(Path.GetDirectoryName(outputPath));
            ConvertGrdToPng(filePath, outputPath);
            Console.WriteLine($"Converted: {filePath} -> {outputPath}");
        }
    }

    static void Main(string[] args)
    {
        if (args.Length != 2)
        {
            Console.WriteLine("Usage: GrdConverter <input> <output>");
            return;
        }

        string input = args[0];
        string output = args[1];

        if (Directory.Exists(input))
        {
            ProcessDirectory(input, output);
        }
        else
        {
            ConvertGrdToPng(input, output);
        }
    }
}