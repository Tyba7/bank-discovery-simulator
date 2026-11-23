import { api, type Feedback as FeedbackData, type ProductCard, type Session } from "../api";

interface Props {
  session: Session;
  feedback: FeedbackData;
  products: ProductCard[];
  onRestart: () => void;
}

const OUTCOME = {
  suitable: "Suitable",
  unsuitable: "Unsuitable",
  investigate: "Check first",
  neutral: "Neutral",
} as const;

const readable = (slug: string) => slug.replace(/_/g, " ").replace(/^./, (c) => c.toUpperCase());

export function Feedback({ session, feedback, onRestart }: Props) {
  const found = feedback.needs.filter((n) => n.discovered).length;
  const recommended = feedback.products.filter((p) => p.recommended);
  const others = feedback.products.filter((p) => !p.recommended);

  return (
    <div className="stack">
      <section>
        <h1>Feedback on your interview with {session.client.name}</h1>
        <p className="lead">
          You uncovered {found} of {feedback.needs.length} hidden needs. Read what went well, what you missed and how to
          ask about it next time.
        </p>
        {feedback.source === "rules" && (
          <div className="alert info" role="status">
            The AI coach was unavailable, so this feedback comes from the bank's rules only. It is still accurate, just
            shorter.
          </div>
        )}
      </section>

      <section className="card">
        <h2>The client's hidden needs</h2>
        <ul className="needs">
          {feedback.needs.map((n) => (
            <li key={n.id} className={n.discovered ? "found" : "missed"}>
              <span className={`badge ${n.discovered ? "good" : "bad"}`}>{n.discovered ? "Uncovered" : "Missed"}</span>
              <div>
                <strong>{readable(n.id)}</strong> <span className="tag">{readable(n.category)}</span>
                <p>{n.fact}</p>
                {n.discovered && n.question && (
                  <p className="muted small">
                    Turn {n.turn}: “{n.question}”
                  </p>
                )}
              </div>
            </li>
          ))}
        </ul>
      </section>

      {feedback.went_well.length > 0 && (
        <section className="card">
          <h2>What went well</h2>
          {feedback.went_well.map((w) => (
            <blockquote key={`${w.turn}-${w.quote}`}>
              <p className="quote">
                Turn {w.turn}: “{w.quote}”
              </p>
              <p>{w.point}</p>
            </blockquote>
          ))}
        </section>
      )}

      {feedback.missed_needs.length > 0 && (
        <section className="card">
          <h2>What you missed</h2>
          {feedback.missed_needs.map((m) => (
            <div key={m.need_id} className="missed-need">
              <h3>{readable(m.need_id)}</h3>
              <p>{m.why_it_matters}</p>
              <p className="try">
                <strong>Try asking:</strong> {m.better_question}
                {m.checked && (
                  <span className="badge good" title="This question was run through the simulator and reveals the need">
                    Tested
                  </span>
                )}
              </p>
            </div>
          ))}
        </section>
      )}

      <section className="card">
        <h2>Products</h2>
        <ProductTable title="Your recommendations" rows={recommended} empty="You did not recommend a product." />
        {others.length > 0 && <ProductTable title="Other products worth knowing about" rows={others} />}
      </section>

      <section className="card">
        <h2>Your summary</h2>
        <p>{feedback.summary.feedback}</p>
      </section>

      <section className="card">
        <h2>Your questions</h2>
        {feedback.question_feedback && <p>{feedback.question_feedback}</p>}
        <p className="muted small">
          {Object.entries(feedback.question_stats)
            .map(([type, n]) => `${n} ${type}`)
            .join(" · ")}
        </p>
        <h3>Next time</h3>
        <ol>
          {feedback.next_steps.map((s) => (
            <li key={s}>{s}</li>
          ))}
        </ol>
      </section>

      <div className="row">
        <a className="button secondary" href={api.exportUrl(session.session_id)} download>
          Download this session
        </a>
        <button className="primary" onClick={onRestart}>
          Start a new interview
        </button>
      </div>
    </div>
  );
}

function ProductTable({ title, rows, empty }: { title: string; rows: FeedbackData["products"]; empty?: string }) {
  return (
    <div className="product-table">
      <h3>{title}</h3>
      {rows.length === 0 && empty && <p className="muted">{empty}</p>}
      {rows.map((p) => (
        <article key={p.id} className={`assessment ${p.outcome}`}>
          <header>
            <strong>{p.name}</strong>
            <span className={`badge ${p.outcome}`}>{OUTCOME[p.outcome]}</span>
          </header>
          {/* The bank's rules come first; the coach only explains them. */}
          <p className="system">
            <span className="label">Assessment</span> {p.assessment}
          </p>
          {p.comment && (
            <p className="explanation">
              <span className="label">Coach</span> {p.comment}
            </p>
          )}
          {p.student_reason && <p className="muted small">Your reason: “{p.student_reason}”</p>}
        </article>
      ))}
    </div>
  );
}
