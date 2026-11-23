import type { ProductCard } from "../api";

export function Catalogue({ products, compact = false }: { products: ProductCard[]; compact?: boolean }) {
  return (
    <section className={compact ? "catalogue compact" : "catalogue"} aria-label="Product catalogue">
      {products.map((p) => (
        <details key={p.id} className="product" open={!compact}>
          <summary>
            <span className="product-name">{p.name}</span>
            <span className="tag">{p.category}</span>
          </summary>
          <div className="product-body">
            <h4>Features</h4>
            <ul>
              {p.features.map((f) => (
                <li key={f}>{f}</li>
              ))}
            </ul>
            <h4>Limitations</h4>
            <ul>
              {p.limitations.map((l) => (
                <li key={l}>{l}</li>
              ))}
            </ul>
          </div>
        </details>
      ))}
    </section>
  );
}
