# Business Requirements Document (BRD)
## Bank Client Discovery Simulator

### 1. Document control

| Field | Value |
|---|---|
| Document | Business Requirements Document |
| Project | Bank Client Discovery Simulator |
| Version | 1.0 |
| Status | Draft for approval |
| Date | 22 November 2026 |
| Author | Tayyaba Rizwan Malik Rizwan Ahmed |
| Reviewers | Assessment panel |

**Revision history**

| Version | Date | Author | Change |
|---|---|---|---|
| 1.0 | 22 Nov 2026 | Tayyaba Rizwan Malik Rizwan Ahmed | First version |

### 2. Executive summary
Students of banking and finance need practice in interviewing clients, understanding their financial needs and recommending suitable products. This project delivers a web application where a student interviews an AI-simulated bank client and receives AI-generated coaching feedback on the interview.

### 3. Business problem
- Role-play practice needs a second person (classmate or instructor), so practice is rare and inconsistent.
- Case studies give all information up front, while real clients reveal important needs only when asked the right questions.
- Feedback on interviews is slow and subjective, so students don't learn which questions they missed.

### 4. Business objectives
| ID | Objective | Measure |
|---|---|---|
| BO-1 | Give students on-demand interview practice | a student can complete a full practice session alone |
| BO-2 | Teach students to uncover hidden client needs through questioning | hidden needs are revealed only by relevant questions |
| BO-3 | Teach students to match products to needs | feedback identifies unsuitable product choices |
| BO-4 | Give feedback that helps students improve | feedback explains what went well, what was missed and how to improve |
| BO-5 | Let instructors maintain scenarios without developers | clients and products can be changed without changing code |

### 5. Scope
**In scope:**
- selecting a fictional client;
- interviewing an AI client;
- viewing and discussing a product catalogue;
- submitting a summary and recommendation;
- receiving AI coaching feedback;
- editable client and product content;
- configurable AI provider.

**Out of scope:**
- user accounts and login;
- storing sessions after the browser is closed;
- grading or scoring students;
- real bank, product or customer data;
- languages other than English.

### 6. Stakeholders
| Stakeholder | Role | Interest |
|---|---|---|
| Students | primary users | realistic practice and useful feedback |
| Instructors | content owners | create and update clients and products |
| Assessment panel | reviewers and sponsors | a working prototype that shows effective use of AI |
| Developer | builds and maintains | clear requirements and acceptance criteria |

### 7. Current state and future state
| | Current state | Future state |
|---|---|---|
| Practice | needs a partner; rare | available any time, alone |
| Client realism | all information given up front | needs revealed only through good questions |
| Feedback | slow, subjective | immediate, structured, specific |
| Content updates | — | instructors edit simple files |

### 8. Business requirements
| ID | Requirement | Priority | Objective |
|---|---|---|---|
| BR-01 | The student shall be able to choose from at least two fictional bank clients, each with a background, financial situation and needs. | Must | BO-1 |
| BR-02 | Each client shall have hidden information (e.g. financial concerns, business challenges, preference for Sharia-compliant banking). | Must | BO-2 |
| BR-03 | The student shall be able to interview the AI client in a chat conversation. | Must | BO-1 |
| BR-04 | The AI client shall stay in character for the whole conversation. | Must | BO-2 |
| BR-05 | The AI client shall respond naturally to the student's questions. | Must | BO-2 |
| BR-06 | The AI client shall reveal hidden information only when the student asks relevant questions. | Must | BO-2 |
| BR-07 | The AI client shall not reveal all its needs at the beginning of the conversation. | Must | BO-2 |
| BR-08 | The system shall provide a catalogue of at least three fictional banking products, with main features and limitations. | Must | BO-3 |
| BR-09 | The student shall be able to discuss products with the AI client during the interview. | Must | BO-3 |
| BR-10 | The student shall be able to submit a summary of the client's needs and their product recommendations. | Must | BO-3 |
| BR-11 | The AI coach shall review the interview against the client's predefined needs and give feedback on what went well. | Must | BO-4 |
| BR-12 | The AI coach shall identify what was missed, including overlooked needs, missing questions and unsuitable product recommendations. | Must | BO-3, BO-4 |
| BR-13 | The AI coach shall give practical suggestions for better questions and more suitable products. | Must | BO-4 |
| BR-14 | Feedback shall help the student learn, not simply give a score. | Must | BO-4 |
| BR-15 | Client profiles, hidden needs and products shall be stored in simple, separate files that can be edited without changing application code. | Must | BO-5 |
| BR-16 | After feedback, the student should be able to see which hidden needs they uncovered. | Should | BO-4 |
| BR-17 | The student should be able to export the session (conversation, summary, feedback). | Should | BO-4 |

### 9. Non-functional requirements
| ID | Category | Requirement | Priority |
|---|---|---|---|
| NFR-01 | AI integration | Both AI chatbots shall use an OpenAI-compatible API. | Must |
| NFR-02 | Configurability | The AI API URL, API key and model name shall be configurable through an environment (`.env`) file, with an example file provided. | Must |
| NFR-03 | Flexibility | The application shall work with a hosted AI provider or a locally hosted model. | Must |
| NFR-04 | Cost | The application shall be usable with free or open-source AI models; no paid subscription required. | Must |
| NFR-05 | Usability | A simple web interface; no login. | Must |
| NFR-06 | Performance | An AI client reply should normally appear within 10 seconds on the tested model. | Should |
| NFR-07 | Reliability | If the AI service is unavailable, the user shall see a clear message instead of an error page. | Should |
| NFR-08 | Security | Hidden client information and API keys shall never be exposed to the browser before feedback. | Must |
| NFR-09 | Quality | AI behaviour (staying in character, controlled disclosure, feedback accuracy) shall be measured with repeatable evaluations. | Should |

### 10. Assumptions
- Students interview in English and have basic banking knowledge.
- Reviewers can run a Python and Node.js application and have access to a hosted AI API key or a local model server.
- All clients, products and the bank are fictional.

### 11. Constraints
- Free or open-source AI models must be supported.
- AI access must use an OpenAI-compatible API.
- No database or user login is required.
- Delivery deadline: 25 November 2026, 12:00 Doha time.

### 12. Dependencies
- An available AI model through an OpenAI-compatible API (hosted provider or local server).

### 13. Risks
| Risk | Impact | Mitigation |
|---|---|---|
| The AI client reveals hidden needs too early | undermines the learning objective | controlled disclosure design + evaluations |
| Students manipulate the AI client ("ignore your instructions") | leaks hidden information | prompt-injection defences + security testing |
| The AI coach gives inaccurate feedback | misleads students | feedback checked against predefined needs |
| A slow or unavailable AI model | poor experience | timeouts, retries, clear error messages |
| Reviewers use a different AI model | unexpected behaviour | tested on a hosted and a local model; documented |

### 14. Success criteria
| ID | Criterion |
|---|---|
| SC-01 | A student completes the workflow: Select Client → Interview → Receive Feedback |
| SC-02 | Hidden needs are revealed only after relevant questions in evaluation tests |
| SC-03 | Feedback lists every missed need and every unsuitable recommended product |
| SC-04 | A reviewer can install, configure and run the application using only the README |
| SC-05 | A new client or product can be added by editing files only |

### 15. Deliverables
| ID | Deliverable |
|---|---|
| DL-01 | GitHub repository with code, sample client data, banking products and `.env.example` |
| DL-02 | README: installation and running, AI configuration, AI provider or local model used for testing |
| DL-03 | One sample interview: conversation, student summary and recommendations, AI coach feedback |

### 16. Glossary
| Term | Definition |
|---|---|
| Client discovery | interviewing a customer to understand their situation and needs before recommending products |
| Hidden need | client information revealed only when the student asks a relevant question |
| Sharia-compliant banking | banking according to Islamic law, without interest |
| OpenAI-compatible API | an AI API that accepts the same request format as OpenAI's Chat Completions API |

### 17. Approval
| Name | Role | Signature | Date |
|---|---|---|---|
| | | | |
