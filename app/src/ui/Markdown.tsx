import * as WebBrowser from "expo-web-browser";
import { View } from "react-native";

import { Text } from "@/theme/components/Text";
import { fontFamily } from "@/theme/type";
import { useTheme } from "@/theme/useTheme";

export type Span = { text: string; bold?: boolean; italic?: boolean; href?: string };
export type Block =
  | { type: "heading"; level: 1 | 2 | 3; spans: Span[] }
  | { type: "paragraph"; spans: Span[] }
  | { type: "list"; ordered: boolean; items: Span[][] };

// Bear tags ("#crypto/staking") have no space after the #, so they stay paragraphs.
const HEADING = /^(#{1,6})\s+(.*)$/;
const TASK = /^[-*]\s+\[( |x|X)\]\s+(.*)$/;
const BULLET = /^[-*+]\s+(.*)$/;
const NUMBERED = /^\d+\.\s+(.*)$/;
// The opening * must not be followed by a space, so "2 * 3 * 4" stays plain.
const INLINE = /\*\*(.+?)\*\*|\*(?!\s)(.+?)(?<!\s)\*|\[([^\]]+)\]\((https?:\/\/[^)\s]+)\)/g;

/** Parses the markdown subset primers and Bear notes use: headings, paragraphs, lists, tasks, links, **bold**, *italic*. */
export function parseMarkdown(text: string): Block[] {
  const blocks: Block[] = [];
  let paragraph: string[] = [];

  const flushParagraph = () => {
    if (paragraph.length > 0) blocks.push({ type: "paragraph", spans: parseSpans(paragraph.join(" ")) });
    paragraph = [];
  };

  for (const rawLine of text.split("\n")) {
    const line = rawLine.trim();
    const heading = HEADING.exec(line);
    const task = TASK.exec(line);
    const bullet = BULLET.exec(line);
    const numbered = NUMBERED.exec(line);

    if (line === "") {
      flushParagraph();
    } else if (heading) {
      flushParagraph();
      blocks.push({ type: "heading", level: Math.min(heading[1].length, 3) as 1 | 2 | 3, spans: parseSpans(heading[2]) });
    } else if (task) {
      flushParagraph();
      const mark = task[1] === " " ? "☐" : "☑";
      appendListItem(blocks, { ordered: false, item: parseSpans(`${mark} ${task[2]}`) });
    } else if (bullet || numbered) {
      flushParagraph();
      appendListItem(blocks, { ordered: Boolean(numbered), item: parseSpans((bullet ?? numbered)![1]) });
    } else {
      paragraph.push(line);
    }
  }
  flushParagraph();

  return blocks;
}

function appendListItem(blocks: Block[], { ordered, item }: { ordered: boolean; item: Span[] }): void {
  const last = blocks[blocks.length - 1];
  if (last?.type === "list" && last.ordered === ordered) {
    last.items.push(item);
    return;
  }
  blocks.push({ type: "list", ordered, items: [item] });
}

function parseSpans(text: string): Span[] {
  // Highlights and strikethrough have no rendering here; only their markers go.
  const plain = text.replace(/==(.+?)==/g, "$1").replace(/~(.+?)~/g, "$1");
  const spans: Span[] = [];
  let cursor = 0;

  for (const match of plain.matchAll(INLINE)) {
    if (match.index > cursor) spans.push({ text: plain.slice(cursor, match.index) });
    spans.push(inlineSpan(match));
    cursor = match.index + match[0].length;
  }
  if (cursor < plain.length) spans.push({ text: plain.slice(cursor) });

  return spans;
}

function inlineSpan(match: RegExpMatchArray): Span {
  if (match[1] !== undefined) return { text: match[1], bold: true };
  if (match[2] !== undefined) return { text: match[2], italic: true };
  return { text: match[3], href: match[4] };
}

export function Markdown({ text }: { text: string }) {
  const theme = useTheme();

  return (
    <View style={{ gap: theme.spacing.md }}>
      {parseMarkdown(text).map((block, index) => (
        <BlockView key={index} block={block} />
      ))}
    </View>
  );
}

function BlockView({ block }: { block: Block }) {
  const theme = useTheme();

  if (block.type === "heading") {
    return (
      <Text variant={block.level === 1 ? "articleTitle" : "headline"}>
        <Spans spans={block.spans} />
      </Text>
    );
  }
  if (block.type === "paragraph") {
    return (
      <Text variant="readingBody">
        <Spans spans={block.spans} />
      </Text>
    );
  }

  return (
    <View style={{ gap: theme.spacing.sm }}>
      {block.items.map((item, index) => (
        <View key={index} style={{ flexDirection: "row", gap: theme.spacing.sm }}>
          <Text variant="readingBody">{block.ordered ? `${index + 1}.` : "•"}</Text>
          <Text variant="readingBody" style={{ flex: 1 }}>
            <Spans spans={item} />
          </Text>
        </View>
      ))}
    </View>
  );
}

// Geist ships static weights, so bold/italic need font-family switches rather than fontWeight.
function Spans({ spans }: { spans: Span[] }) {
  return (
    <>
      {spans.map((span, index) => (
        <Text
          key={index}
          variant="readingBody"
          style={{
            fontFamily: span.bold ? fontFamily.bold : undefined,
            fontStyle: span.italic ? "italic" : undefined,
            textDecorationLine: span.href ? "underline" : undefined,
          }}
          onPress={span.href ? () => void WebBrowser.openBrowserAsync(span.href!) : undefined}
        >
          {span.text}
        </Text>
      ))}
    </>
  );
}
