// A tiny, safe renderer for the assistant's answers: **bold**, "- " bullets and paragraphs, nothing else.
// It returns data (not HTML), so whatever the model wrote can never inject markup.

/** "a **b** c" -> [{t:'a '},{t:'b',b:true},{t:' c'}] */
export function inline(text) {
  const out = [];
  String(text).split(/(\*\*[^*]+\*\*)/g).forEach((part) => {
    if (!part) return;
    if (part.startsWith('**') && part.endsWith('**') && part.length > 4) out.push({ t: part.slice(2, -2), b: true });
    else out.push({ t: part });
  });
  return out;
}

/** -> [{type:'h'|'p'|'li', parts}] ; a line that is only **bold** is a heading */
export function blocks(text) {
  const out = [];
  String(text || '').split('\n').forEach((raw) => {
    const line = raw.trim();
    if (!line) return;
    const bullet = line.match(/^[-*•]\s+(.*)$/);
    if (bullet) { out.push({ type: 'li', parts: inline(bullet[1]) }); return; }
    const head = line.match(/^\*\*([^*]+)\*\*:?$/);
    if (head) { out.push({ type: 'h', parts: [{ t: head[1], b: true }] }); return; }
    const prev = out[out.length - 1];
    if (prev && prev.type === 'p') prev.parts.push({ t: ' ' }, ...inline(line));
    else out.push({ type: 'p', parts: inline(line) });
  });
  return out;
}
