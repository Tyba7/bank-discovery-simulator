import { useEffect, useState } from "react";
import { api, ApiError, type ClientCard, type Feedback as FeedbackData, type ProductCard, type Session } from "./api";
import { Feedback } from "./screens/Feedback";
import { Interview } from "./screens/Interview";
import { SelectClient } from "./screens/SelectClient";
import { Submit } from "./screens/Submit";

type Step = "select" | "interview" | "submit" | "feedback";
const STEPS: { id: Step; label: string }[] = [
  { id: "select", label: "Choose a client" },
  { id: "interview", label: "Interview" },
  { id: "submit", label: "Summary" },
  { id: "feedback", label: "Feedback" },
];
const SESSION_KEY = "discovery-session";

function storedSession(): string | null {
  try {
    return sessionStorage.getItem(SESSION_KEY);
  } catch {
    return null;
  }
}

function storeSession(id: string | null) {
  try {
    if (id) sessionStorage.setItem(SESSION_KEY, id);
    else sessionStorage.removeItem(SESSION_KEY);
  } catch {
    // storage blocked: the session simply does not survive a reload
  }
}

export default function App() {
  const [step, setStep] = useState<Step>("select");
  const [clients, setClients] = useState<ClientCard[]>([]);
  const [products, setProducts] = useState<ProductCard[]>([]);
  const [session, setSession] = useState<Session | null>(null);
  const [feedback, setFeedback] = useState<FeedbackData | null>(null);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    Promise.all([api.clients(), api.products()])
      .then(([c, p]) => {
        setClients(c);
        setProducts(p);
      })
      .catch((e: ApiError) => setError(e.message));
    const id = storedSession();
    if (id) {
      api
        .session(id)
        .then((s) => {
          setSession(s);
          setFeedback(s.feedback);
          setStep(s.finished ? "feedback" : "interview");
        })
        .catch(() => storeSession(null)); // expired: start fresh
    }
  }, []);

  const begin = (s: Session) => {
    storeSession(s.session_id);
    setSession(s);
    setFeedback(null);
    setStep("interview");
  };

  const restart = () => {
    storeSession(null);
    setSession(null);
    setFeedback(null);
    setStep("select");
  };

  return (
    <div className="app">
      <header className="topbar">
        <div className="brand">
          <span className="brand-mark" aria-hidden="true">
            ◆
          </span>
          Client Discovery Simulator
        </div>
        <ol className="steps" aria-label="Progress">
          {STEPS.map((s, i) => (
            <li key={s.id} className={s.id === step ? "current" : ""} aria-current={s.id === step ? "step" : undefined}>
              <span className="step-number">{i + 1}</span>
              {s.label}
            </li>
          ))}
        </ol>
      </header>

      <main className="content">
        {error && (
          <div className="alert" role="alert">
            {error}
          </div>
        )}
        {step === "select" && <SelectClient clients={clients} products={products} onStarted={begin} />}
        {step === "interview" && session && (
          <Interview
            session={session}
            products={products}
            onChange={setSession}
            onFinish={() => setStep("submit")}
            onRestart={restart}
          />
        )}
        {step === "submit" && session && (
          <Submit
            session={session}
            products={products}
            onBack={() => setStep("interview")}
            onFeedback={(f) => {
              setFeedback(f);
              setStep("feedback");
            }}
          />
        )}
        {step === "feedback" && session && feedback && (
          <Feedback session={session} feedback={feedback} products={products} onRestart={restart} />
        )}
      </main>
    </div>
  );
}
