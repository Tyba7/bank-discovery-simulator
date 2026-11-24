import { render, screen, waitFor, within } from "@testing-library/react";
import { useState } from "react";
import userEvent from "@testing-library/user-event";
import { afterEach, describe, expect, it, vi } from "vitest";
import type { Feedback as FeedbackData, Session } from "./api";
import { Feedback } from "./screens/Feedback";
import { ChatMessage, Interview } from "./screens/Interview";

const ATTACK = `<img src=x onerror="alert('xss')"><script>alert('xss')</script>`;

const session: Session = {
  session_id: "s1",
  client: {
    id: "maria_santos",
    name: "Maria Santos",
    age: 35,
    occupation: "Nurse",
    background: "Six years in Qatar.",
    stated_goal: "Open a savings account.",
  },
  messages: [{ role: "client", content: "Good morning." }],
  turns_left: 40,
  finished: false,
  feedback: null,
};

function respond(status: number, body: unknown) {
  return vi.fn().mockResolvedValue(new Response(JSON.stringify(body), { status }));
}

afterEach(() => vi.unstubAllGlobals());

describe("chat messages", () => {
  it("show model and student text as text, never as HTML", () => {
    const { container } = render(
      <>
        <ChatMessage message={{ role: "client", content: ATTACK }} clientName="Maria" />
        <ChatMessage message={{ role: "student", content: ATTACK }} clientName="Maria" />
      </>,
    );
    expect(container.querySelector("img, script")).toBeNull();
    expect(screen.getAllByText(ATTACK)).toHaveLength(2);
  });
});

describe("interview", () => {
  it("puts the question back in the box when the model is down", async () => {
    vi.stubGlobal("fetch", respond(503, { detail: "The AI service is not responding right now." }));
    const onChange = vi.fn();
    render(<Interview session={session} products={[]} onChange={onChange} onFinish={vi.fn()} onRestart={vi.fn()} />);
    await userEvent.type(screen.getByLabelText("Your question"), "What are you saving for?{Enter}");
    expect(await screen.findByRole("alert")).toHaveTextContent("The AI service is not responding right now.");
    expect(screen.getByLabelText("Your question")).toHaveValue("What are you saving for?");
    await waitFor(() => expect(onChange).toHaveBeenLastCalledWith({ ...session, messages: session.messages }));
  });
});

describe("interview in a current browser", () => {
  it("does not crash when scrollIntoView returns a Promise", async () => {
    // Newer Chrome returns a Promise; an effect that returned it crashed the page on the first message.
    Element.prototype.scrollIntoView = vi.fn().mockResolvedValue(undefined);
    vi.stubGlobal("fetch", respond(200, { reply: "For my children's university.", turns_left: 39 }));
    function Harness() {
      const [s, setS] = useState(session);
      return <Interview session={s} products={[]} onChange={setS} onFinish={vi.fn()} onRestart={vi.fn()} />;
    }
    render(<Harness />);
    await userEvent.type(screen.getByLabelText("Your question"), "What are you saving for?{Enter}");
    expect(await screen.findByText("For my children's university.")).toBeInTheDocument();
  });
});

describe("feedback", () => {
  const feedback: FeedbackData = {
    client_id: "maria_santos",
    source: "coach",
    needs: [
      {
        id: "low_risk_tolerance",
        category: "risk_tolerance",
        topic: "",
        fact: "Wants no risk.",
        discovered: false,
        turn: null,
        question: null,
      },
    ],
    went_well: [],
    missed_needs: [],
    products: [
      {
        id: "equity_growth_fund",
        name: "Equity Growth Fund",
        recommended: true,
        student_reason: "growth",
        discussed_turns: [],
        verdict: "unsuitable",
        outcome: "unsuitable",
        reasons: [],
        to_check: [],
        assessment: "Unsuitable. The value can fall.",
        comment: ATTACK,
      },
    ],
    summary: { confirmed: [], left_out: [], unconfirmed: [], feedback: "ok" },
    question_feedback: "",
    next_steps: ["Ask about risk."],
    question_stats: {},
  };

  it("shows the rules' assessment before the coach's comment, and escapes the comment", () => {
    const { container } = render(<Feedback session={session} feedback={feedback} products={[]} onRestart={vi.fn()} />);
    const system = screen.getByText("Unsuitable. The value can fall.");
    const coach = screen.getByText(ATTACK);
    expect(system.compareDocumentPosition(coach) & Node.DOCUMENT_POSITION_FOLLOWING).toBeTruthy();
    expect(container.querySelector("img, script")).toBeNull();
    expect(screen.getByText("Missed")).toBeInTheDocument();
  });

  it("groups the feedback under the brief's three areas", () => {
    render(<Feedback session={session} feedback={feedback} products={[]} onRestart={vi.fn()} />);
    const area = (name: string) => screen.getByRole("heading", { level: 2, name }).closest("section") as HTMLElement;
    // an unsuitable recommendation is something missed, not a product note on its own
    expect(within(area("What was missed")).getByText("Equity Growth Fund")).toBeInTheDocument();
    expect(within(area("What went well")).getByText(/Nothing stood out/)).toBeInTheDocument();
    expect(within(area("How to improve")).getByText("Ask about risk.")).toBeInTheDocument();
  });
});
