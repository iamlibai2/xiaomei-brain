import React from "react";
import ReactMarkdown from "react-markdown";
import { Prism as SyntaxHighlighter } from "react-syntax-highlighter";
import { oneDark } from "react-syntax-highlighter/dist/esm/styles/prism";

interface Props {
  role: "user" | "agent" | "tool";
  content: string;
}

export function MessageBubble({ role, content }: Props) {
  if (role === "tool") {
    return (
      <div className="message-tool">
        <span className="tool-label">[TOOL]</span> {content}
      </div>
    );
  }

  return (
    <div className={`message-bubble ${role}`}>
      {role === "agent" ? (
        <ReactMarkdown
          components={{
            code({ className, children, ...props }) {
              const match = /language-(\w+)/.exec(className || "");
              const code = String(children).replace(/\n$/, "");
              if (match) {
                return (
                  <SyntaxHighlighter
                    style={oneDark}
                    language={match[1]}
                    PreTag="div"
                  >
                    {code}
                  </SyntaxHighlighter>
                );
              }
              return (
                <code className={className} {...props}>
                  {children}
                </code>
              );
            },
          }}
        >
          {content}
        </ReactMarkdown>
      ) : (
        <p>{content}</p>
      )}
    </div>
  );
}
