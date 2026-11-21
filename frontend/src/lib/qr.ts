// A QR code as one SVG path, from the rows of 0 and 1 the server computes. No image, no inline style: the page's policy allows neither.

/** One small square per dark cell, shifted by the quiet zone that scanners need around the code. */
export function qrPath(rows: string[], margin: number): string {
  const parts: string[] = [];
  rows.forEach((row, y) => {
    for (let x = 0; x < row.length; x += 1) {
      if (row[x] === "1") parts.push(`M${x + margin} ${y + margin}h1v1h-1z`);
    }
  });
  return parts.join("");
}
