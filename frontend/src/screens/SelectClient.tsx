import { useState } from "react";
import { api, ApiError, type ClientCard, type ProductCard, type Session } from "../api";
import { Catalogue } from "./Catalogue";

interface Props {
  clients: ClientCard[];
  products: ProductCard[];
  onStarted: (session: Session) => void;
}

export function SelectClient({ clients, products, onStarted }: Props) {
  const [starting, setStarting] = useState<string | null>(null);
  const [error, setError] = useState<string | null>(null);

  const start = async (id: string) => {
    setStarting(id);
    setError(null);
    try {
      onStarted(await api.start(id));
    } catch (e) {
      setError((e as ApiError).message);
    } finally {
      setStarting(null);
    }
  };

  return (
    <div className="stack">
      <section>
        <h1>Choose a client to interview</h1>
        <p className="lead">
          Each client has needs they will only share if you ask the right questions. Find out as much as you can, then
          write a summary and recommend products. The coach will review your interview.
        </p>
      </section>

      {error && (
        <div className="alert" role="alert">
          {error}
        </div>
      )}

      <div className="client-grid">
        {clients.map((c) => (
          <article key={c.id} className="card client-card">
            <div className="avatar" aria-hidden="true">
              {c.name
                .split(" ")
                .map((w) => w[0])
                .join("")}
            </div>
            <h2>{c.name}</h2>
            <p className="muted">
              {c.age}, {c.occupation}
            </p>
            <p>{c.background}</p>
            <p>
              <strong>Why they came in:</strong> {c.stated_goal}
            </p>
            <button className="primary" disabled={starting !== null} onClick={() => start(c.id)}>
              {starting === c.id ? "Starting…" : `Interview ${c.name.split(" ")[0]}`}
            </button>
          </article>
        ))}
      </div>

      <section>
        <h2>Product catalogue</h2>
        <p className="muted">You can discuss these products with the client during the interview.</p>
        <Catalogue products={products} compact />
      </section>
    </div>
  );
}
