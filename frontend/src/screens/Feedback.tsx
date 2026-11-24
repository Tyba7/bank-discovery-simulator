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

// Products the student did not recommend, best fit first: "how to improve" points to the better choices.
const FIT_ORDER = ["suitable", "investigate", "neutral", "unsuitable"];

const readable = (slug: string) => slug.replace(/_/g, " ").replace(/^./, (c) => c.toUpperCase());

export function Feedback({ session, feedback, onRestart }: Props) {
  const found = feedback.needs.filter((n) => n.discovered).length;
  const recommended = feedback.products.filter((p) => p.recommended);
  const fits = recommended.filter((p) => p.outcome === "suitable" || p.outcome === "neutral");
  const rethink = recommended.filter((p) => p.outcome === "unsuitable" || p.outcome === "investigate");
  const others = feedback.products
    .filter((p) => !p.recommended)
    .sort((a, b) => FIT_ORDER.indexOf(a.outcome) - FIT_ORDER.indexOf(b.outcome));

  return (
    <div className="stack">
      <section>
        <h1>Feedback on your interview with {session.client.name}</h1>
        <p className="lead">
          You uncovered {found} of {feedback.needs.length} hidden needs. Read what went well, what was missed and how to
          improve.
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

      <section className="card">
        <h2>What went well</h2>
        {feedback.went_well.length === 0 && fits.length === 0 && (
          <p className="muted">Nothing stood out this time. The next two sections show what to change.</p>
        )}
        {feedback.went_well.map((w) => (
          <blockquote key={`${w.turn}-${w.quote}`}>
            <p className="quote">
              Turn {w.turn}: “{w.quote}”
            </p>
            <p>{w.point}</p>
          </blockquote>
        ))}
        {fits.length > 0 && <ProductTable title="Your recommendations that fit" rows={fits} />}
      </section>

      <section className="card">
        <h2>What was missed</h2>
        {feedback.missed_needs.length === 0 && <p className="muted">You uncovered every hidden need.</p>}
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
        {recommended.length === 0 && <p className="muted">You did not recommend a product.</p>}
        {rethink.length > 0 && <ProductTable title="Recommendations to rethink" rows={rethink} />}
      </section>

      <section className="card">
        <h2>How to improve</h2>
        <h3>Your questions</h3>
        {feedback.question_feedback && <p>{feedback.question_feedback}</p>}
        <p className="muted small">
          {Object.entries(feedback.question_stats)
            .map(([type, n]) => `${n} ${type}`)
            .join(" · ")}
        </p>
        {others.length > 0 && <ProductTable title="Other products and how they fit" rows={others} />}
        <h3>Your summary</h3>
        <p>{feedback.summary.feedback}</p>
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

function ProductTable({ title, rows }: { title: string; rows: FeedbackData["products"] }) {
  return (
    <div className="product-table">
      <h3>{title}</h3>
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
