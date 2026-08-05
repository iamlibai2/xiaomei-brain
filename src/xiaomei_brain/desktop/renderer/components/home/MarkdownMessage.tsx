import {
  Component,
  createContext,
  isValidElement,
  memo,
  type ErrorInfo,
  type MouseEvent,
  type ReactNode,
  useEffect,
  useId,
  useContext,
  useRef,
  useState,
} from "react";
import ReactMarkdown, { type Components } from "react-markdown";
import rehypeHighlight from "rehype-highlight";
import rehypeKatex from "rehype-katex";
import rehypeSanitize, { defaultSchema } from "rehype-sanitize";
import remarkBreaks from "remark-breaks";
import remarkGfm from "remark-gfm";
import remarkMath from "remark-math";
import "katex/dist/katex.min.css";
import { Icon } from "../ui";
import { useTranslation } from "react-i18next";
import i18n from "../../i18n";

const MarkdownStreamingContext = createContext(false);
let mermaidRenderQueue: Promise<void> = Promise.resolve();

function renderMermaid(id: string, source: string): Promise<string> {
  let rendered = "";
  const job = mermaidRenderQueue.then(async () => {
    const { default: mermaid } = await import("mermaid");
    mermaid.initialize({
      startOnLoad: false,
      securityLevel: "strict",
      suppressErrorRendering: true,
      theme: document.documentElement.dataset.theme === "dark" ? "dark" : "default",
      fontFamily: "inherit",
    });
    const result = await mermaid.render(id, source);
    rendered = result.svg;
  });
  mermaidRenderQueue = job.then(() => undefined, () => undefined);
  return job.then(() => rendered);
}

const sanitizeSchema = {
  ...defaultSchema,
  attributes: {
    ...defaultSchema.attributes,
    code: [...(defaultSchema.attributes?.code || []), ["className", /^language-./]],
    div: [...(defaultSchema.attributes?.div || []), ["className", /^math-display$/]],
    input: [
      ...(defaultSchema.attributes?.input || []),
      ["type", "checkbox"],
      "checked",
      "disabled",
    ],
    span: [
      ...(defaultSchema.attributes?.span || []),
      ["className", /^(hljs|hljs-.+|katex.*|math.*)$/],
      "style",
    ],
  },
};

function nodeText(node: ReactNode): string {
  if (typeof node === "string" || typeof node === "number") return String(node);
  if (Array.isArray(node)) return node.map(nodeText).join("");
  if (isValidElement<{ children?: ReactNode }>(node)) return nodeText(node.props.children);
  return "";
}

function safeDownloadName(language: string): string {
  const normalized = language.replace(/[^a-z0-9_-]/gi, "").toLowerCase();
  return normalized === "mermaid" ? "diagram.svg" : `code.${normalized || "txt"}`;
}

function downloadText(content: string, fileName: string, type = "text/plain;charset=utf-8"): void {
  const url = URL.createObjectURL(new Blob([content], { type }));
  const anchor = document.createElement("a");
  anchor.href = url;
  anchor.download = fileName;
  anchor.click();
  URL.revokeObjectURL(url);
}

function MermaidBlock({ source, streaming }: { source: string; streaming: boolean }) {
  const { t } = useTranslation();
  const id = useId().replace(/[^a-z0-9]/gi, "");
  const [svg, setSvg] = useState("");
  const [error, setError] = useState("");
  const [showSource, setShowSource] = useState(false);
  const [expanded, setExpanded] = useState(false);

  useEffect(() => {
    if (streaming) {
      setError("");
      setSvg("");
      return;
    }
    let cancelled = false;
    setError("");
    setSvg("");

    void renderMermaid(`mermaid-${id}-${Date.now()}`, source)
      .then((result) => {
        if (!cancelled) setSvg(result);
      })
      .catch((reason: unknown) => {
        if (!cancelled) setError(reason instanceof Error ? reason.message : String(reason));
      });

    return () => {
      cancelled = true;
    };
  }, [id, source, streaming]);

  const diagram = (
    <div className="md-mermaid-canvas">
      {!svg && !error && (
        <div className="md-mermaid-loading">
          {streaming ? t("markdownUi.generating") : t("markdownUi.drawing")}
        </div>
      )}
      {error && (
        <div className="md-mermaid-error">
          {t("markdownUi.parseFailed")}
          <span>{error}</span>
        </div>
      )}
      {svg && <div dangerouslySetInnerHTML={{ __html: svg }} />}
    </div>
  );

  return (
    <div className="md-mermaid">
      <div className="md-mermaid-toolbar">
        <span>Mermaid</span>
        <div>
          <button type="button" onClick={() => setShowSource((value) => !value)}>
            {showSource ? t("markdownUi.viewDiagram") : t("markdownUi.viewSource")}
          </button>
          {svg && (
            <>
              <button type="button" onClick={() => setExpanded(true)}>{t("markdownUi.zoom")}</button>
              <button
                type="button"
                onClick={() => downloadText(svg, safeDownloadName("mermaid"), "image/svg+xml;charset=utf-8")}
              >
                {t("markdownUi.download")}
              </button>
            </>
          )}
        </div>
      </div>
      {showSource ? <pre><code>{source}</code></pre> : diagram}
      {expanded && (
        <div className="md-mermaid-overlay" role="dialog" aria-modal="true" onClick={() => setExpanded(false)}>
          <button type="button" className="md-mermaid-close" onClick={() => setExpanded(false)}>{t("markdownUi.close")}</button>
          <div className="md-mermaid-expanded" onClick={(event) => event.stopPropagation()}>
            {diagram}
          </div>
        </div>
      )}
    </div>
  );
}

function CodeBlock({
  className,
  children,
  node: _node,
  ...props
}: React.ComponentPropsWithoutRef<"code"> & { node?: unknown }) {
  const { t } = useTranslation();
  const language = /language-([\w-]+)/.exec(className || "")?.[1] || "";
  const streaming = useContext(MarkdownStreamingContext);
  const source = nodeText(children).replace(/\n$/, "");
  const isInline = !language && !source.includes("\n");
  const [copied, setCopied] = useState(false);
  const copyTimerRef = useRef<number>();

  useEffect(() => () => window.clearTimeout(copyTimerRef.current), []);

  if (isInline) {
    return <code className={className} {...props}>{children}</code>;
  }
  if (language.toLowerCase() === "mermaid") {
    return <MermaidBlock source={source} streaming={streaming} />;
  }

  const copy = async () => {
    await navigator.clipboard.writeText(source);
    setCopied(true);
    window.clearTimeout(copyTimerRef.current);
    copyTimerRef.current = window.setTimeout(() => setCopied(false), 1600);
  };

  return (
    <div className="md-code-block">
      <div className="md-pre-header">
        <span className="md-pre-lang">{language || "code"}</span>
        <button type="button" className="md-pre-copy" onClick={() => void copy()}>
          <Icon name="copy" size={14} />
          {copied ? t("markdownUi.copied") : t("markdownUi.copy")}
        </button>
      </div>
      <pre><code className={className} {...props}>{children}</code></pre>
    </div>
  );
}

function openMarkdownLink(event: MouseEvent<HTMLAnchorElement>, href?: string): void {
  if (!href || href.startsWith("#")) return;
  event.preventDefault();
  void window.desktop.openExternal(href);
}

const markdownComponents: Components = {
  table({ children }) {
    return <div className="md-table-wrapper"><table>{children}</table></div>;
  },
  pre({ children }) {
    return <div className="md-pre-wrapper">{children}</div>;
  },
  code: CodeBlock,
  a({ href, children, ...props }) {
    return (
      <a
        href={href}
        {...props}
        rel="noopener noreferrer"
        onClick={(event) => openMarkdownLink(event, href)}
      >
        {children}
        {href && !href.startsWith("#") && <Icon name="external-link" size={12} />}
      </a>
    );
  },
  img({ src, alt, ...props }) {
    return (
      <button
        type="button"
        className="md-image-button"
        title={alt || i18n.t("markdownUi.openImage")}
        onClick={() => src && void window.desktop.openExternal(src)}
      >
        <img src={src} alt={alt || ""} loading="lazy" {...props} />
      </button>
    );
  },
};

class MarkdownErrorBoundary extends Component<
  { children: ReactNode; source: string },
  { failed: boolean }
> {
  state = { failed: false };

  static getDerivedStateFromError(): { failed: boolean } {
    return { failed: true };
  }

  componentDidCatch(error: Error, info: ErrorInfo): void {
    console.error("[markdown] render failed", error, info.componentStack);
  }

  componentDidUpdate(previous: Readonly<{ children: ReactNode; source: string }>): void {
    if (this.state.failed && previous.source !== this.props.source) {
      this.setState({ failed: false });
    }
  }

  render(): ReactNode {
    if (this.state.failed) {
      return <div className="message-md md-render-fallback">{this.props.source}</div>;
    }
    return this.props.children;
  }
}

function normalizeMathDelimiters(markdown: string): string {
  // remark-math recognizes dollar delimiters. LLMs also frequently emit the
  // equivalent LaTeX delimiters, which CommonMark would otherwise unescape
  // into plain parentheses or brackets before remark-math sees them.
  return markdown
    .split(/(```[\s\S]*?(?:```|$)|~~~[\s\S]*?(?:~~~|$))/g)
    .map((part) => {
      if (part.startsWith("```") || part.startsWith("~~~")) return part;
      return part
        .replace(/\\\[([\s\S]*?)\\\]/g, (_match, formula: string) => (
          `\n$$\n${formula.trim()}\n$$\n`
        ))
        .replace(/\\\(([\s\S]*?)\\\)/g, (_match, formula: string) => (
          `$${formula.trim()}$`
        ))
        // Some model/provider combinations drop the escaping slash from the
        // outer brackets while preserving TeX commands inside the formula.
        .replace(
          /(^|\n)([ \t]*)\[([^\]]*(?:\\[a-zA-Z]+|[_^{}])[^\]]*)\](?=[ \t]*(?:\n|$))/g,
          (_match, prefix: string, _indent: string, formula: string) => (
            `${prefix}$$\n${formula.trim()}\n$$`
          ),
        );
    })
    .join("");
}

export const MarkdownMessage = memo(function MarkdownMessage({
  content,
  streaming = false,
}: {
  content: string;
  streaming?: boolean;
}) {
  const normalizedContent = normalizeMathDelimiters(content);
  return (
    <MarkdownStreamingContext.Provider value={streaming}>
      <MarkdownErrorBoundary source={content}>
        <ReactMarkdown
          className="message-md"
          remarkPlugins={[remarkGfm, remarkBreaks, [remarkMath, { singleDollarTextMath: true }]]}
          rehypePlugins={[
            [rehypeSanitize, sanitizeSchema],
            rehypeKatex,
            [rehypeHighlight, { detect: false, plainText: ["mermaid"] }],
          ]}
          components={markdownComponents}
        >
          {normalizedContent}
        </ReactMarkdown>
      </MarkdownErrorBoundary>
    </MarkdownStreamingContext.Provider>
  );
});
