import { parseSSE } from "./sse";

function stream(chunks: string[]) {
  const enc = new TextEncoder();
  return new ReadableStream<Uint8Array>({
    start(c) {
      chunks.forEach((x) => c.enqueue(enc.encode(x)));
      c.close();
    },
  });
}

test("events split across chunks are reassembled", async () => {
  const events = [];
  const s = stream([
    'event: conversation\ndata: {"type":"conversation","id":"conv-1"}\n\nevent: texte\ndata: {"type":"te',
    'xte","texte":"Bon"}\n\n',
    'event: texte\r\ndata: {"type":"texte","texte":"jour"}\r\n\r\n',
  ]);
  for await (const e of parseSSE(s)) events.push(e);
  expect(events).toEqual([
    { type: "conversation", id: "conv-1" },
    { type: "texte", texte: "Bon" },
    { type: "texte", texte: "jour" },
  ]);
});
