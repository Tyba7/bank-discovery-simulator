import { type FormEvent, type KeyboardEvent, useEffect, useRef, useState } from "react";
import { api, ApiError, MAX_MESSAGE_CHARS, type Message, type ProductCard, type Session } from "../api";
import { Catalogue } from "./Catalogue";

const SLOW_TURN_MS = 15_000;

interface Props {
  session: Session;
  products: ProductCard[];
  onChange: (session: Session) => void;
  onFinish: () => void;
  onRestart: () => void;
}

export function ChatMessage({ message, clientName }: { message: Message; clientName: string }) {
  // Text only: React escapes it, and nothing here renders HTML from the model or the student.
  return (
    <div className={`bubble ${message.role}`}>
      <span className="speaker">{message.role === "student" ? "You" : clientName}</span>
      <p>{message.content}</p>
    </div>
  );
}

export function Interview({ session, products, onChange, onFinish, onRestart }: Props) {
  const [draft, setDraft] = useState("");
  const [pending, setPending] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [slow, setSlow] = useState(false);
  const endRef = useRef<HTMLDivElement>(null);
  const firstName = session.client.name.split(" ")[0];
  const studentTurns = session.messages.filter((m) => m.role === "student").length;

  useEffect(() => {
    // A block body on purpose: newer browsers return a Promise from scrollIntoView, and React must get no cleanup value.
    endRef.current?.scrollIntoView?.({ behavior: "smooth", block: "end" });
  }, [session.messages, pending]);

  useEffect(() => {
    // One turn can take several model calls; on a slow model, say so instead of looking frozen.
    setSlow(false);
    if (!pending) return;
    const timer = setTimeout(() => setSlow(true), SLOW_TURN_MS);
    return () => clearTimeout(timer);
  }, [pending]);

  const send = async (e?: FormEvent) => {
    e?.preventDefault();
    const text = draft.trim();
    if (!text || pending) return;
    setPending(true);
    setError(null);
    setDraft("");
    const shown = [...session.messages, { role: "student", content: text } as Message];
    onChange({ ...session, messages: shown });
    try {
      const r = await api.send(session.session_id, text);
      onChange({ ...session, messages: [...shown, { role: "client", content: r.reply }], turns_left: r.turns_left });
    } catch (err) {
      // The server rolls a failed turn back, so the screen does too: the question goes back into the box.
      onChange({ ...session, messages: session.messages });
      setDraft(text);
      setError((err as ApiError).message);
    } finally {
      setPending(false);
    }
  };

  const onKey = (e: KeyboardEvent<HTMLTextAreaElement>) => {
    if (e.key === "Enter" && !e.shiftKey) {
      e.preventDefault();
      void send();
    }
  };

  return (
    <div className="interview">
      <section className="chat card" aria-label={`Interview with ${session.client.name}`}>
        <div className="chat-log" aria-live="polite">
          {session.messages.map((m, i) => (
            <ChatMessage key={i} message={m} clientName={firstName} />
          ))}
          {pending && (
            <div className="bubble client typing" role="status" aria-label={`${firstName} is replying`}>
              <span className="speaker">{firstName}</span>
              <p>
                <span className="dots" aria-hidden="true">
                  <i />
                  <i />
                  <i />
                </span>
              </p>
            </div>
          )}
          {slow && (
            <p className="muted small" role="status">
              Still working on a reply. On a slow model this can take up to a minute; your question is safe.
            </p>
          )}
          <div ref={endRef} />
        </div>

        {error && (
          <div className="alert" role="alert">
            {error}
          </div>
        )}

        <form className="composer" onSubmit={send}>
          <label htmlFor="message" className="sr-only">
            Your question
          </label>
          <textarea
            id="message"
            value={draft}
            maxLength={MAX_MESSAGE_CHARS}
            rows={2}
            placeholder={`Ask ${firstName} a question… (Enter to send, Shift+Enter for a new line)`}
            onChange={(e) => setDraft(e.target.value)}
            onKeyDown={onKey}
            disabled={session.turns_left <= 0}
          />
          <div className="composer-bar">
            <span className="muted small">
              {draft.length}/{MAX_MESSAGE_CHARS} · {session.turns_left} questions left
            </span>
            <button className="primary" type="submit" disabled={pending || !draft.trim() || session.turns_left <= 0}>
              Send
            </button>
          </div>
        </form>
      </section>

      <aside className="sidebar">
        <div className="card">
          <h2>{session.client.name}</h2>
          <p className="muted">
            {session.client.age}, {session.client.occupation}
          </p>
          <p>{session.client.background}</p>
          <p>
            <strong>Why they came in:</strong> {session.client.stated_goal}
          </p>
        </div>
        <div className="card actions">
          <button className="primary" onClick={onFinish} disabled={pending || studentTurns === 0}>
            Finish and write summary
          </button>
          <button className="link" onClick={onRestart} disabled={pending}>
            Start over with another client
          </button>
        </div>
        <div className="card">
          <h2>Products</h2>
          <Catalogue products={products} compact />
        </div>
      </aside>
    </div>
  );
}
