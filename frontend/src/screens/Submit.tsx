import { type FormEvent, useState } from "react";
import {
  api,
  ApiError,
  type Feedback,
  MAX_REASON_CHARS,
  MAX_SUMMARY_CHARS,
  type ProductCard,
  type Session,
} from "../api";

interface Props {
  session: Session;
  products: ProductCard[];
  onBack: () => void;
  onFeedback: (feedback: Feedback) => void;
}

export function Submit({ session, products, onBack, onFeedback }: Props) {
  const [summary, setSummary] = useState("");
  const [chosen, setChosen] = useState<Record<string, string>>({}); // product id -> reason
  const [pending, setPending] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const toggle = (id: string) =>
    setChosen(({ [id]: removed, ...rest }) => (removed === undefined ? { ...rest, [id]: "" } : rest));

  const submit = async (e: FormEvent) => {
    e.preventDefault();
    setPending(true);
    setError(null);
    try {
      const recs = Object.entries(chosen).map(([product_id, reason]) => ({ product_id, reason: reason.trim() }));
      onFeedback(await api.feedback(session.session_id, summary.trim(), recs));
    } catch (err) {
      setError((err as ApiError).message);
    } finally {
      setPending(false);
    }
  };

  return (
    <form className="stack narrow" onSubmit={submit}>
      <section>
        <h1>Summarise {session.client.name.split(" ")[0]}'s needs</h1>
        <p className="lead">
          Write what you learned about the client, then choose the products you would recommend and say why. After you
          submit, the interview ends and the coach reviews it.
        </p>
      </section>

      <div className="card">
        <label htmlFor="summary">
          <h2>Summary of the client's needs</h2>
        </label>
        <textarea
          id="summary"
          rows={6}
          value={summary}
          maxLength={MAX_SUMMARY_CHARS}
          onChange={(e) => setSummary(e.target.value)}
          placeholder="Their goals, financial situation, commitments, attitude to risk and any preferences…"
        />
        <p className="muted small">
          {summary.length}/{MAX_SUMMARY_CHARS}
        </p>
      </div>

      <fieldset className="card">
        <legend>
          <h2>Your recommendations</h2>
        </legend>
        {products.map((p) => (
          <div key={p.id} className={`rec ${p.id in chosen ? "chosen" : ""}`}>
            <label className="check">
              <input type="checkbox" checked={p.id in chosen} onChange={() => toggle(p.id)} />
              <span>
                <strong>{p.name}</strong> <span className="tag">{p.category}</span>
              </span>
            </label>
            {p.id in chosen && (
              <input
                type="text"
                aria-label={`Why you recommend ${p.name}`}
                placeholder="Why this product fits the client"
                maxLength={MAX_REASON_CHARS}
                value={chosen[p.id]}
                onChange={(e) => setChosen({ ...chosen, [p.id]: e.target.value })}
              />
            )}
          </div>
        ))}
      </fieldset>

      {error && (
        <div className="alert" role="alert">
          {error}
        </div>
      )}

      <div className="row">
        <button type="button" className="secondary" onClick={onBack} disabled={pending}>
          Back to the interview
        </button>
        <button type="submit" className="primary" disabled={pending}>
          {pending ? "The coach is reviewing your interview… (up to a minute)" : "Submit for feedback"}
        </button>
      </div>
    </form>
  );
}
