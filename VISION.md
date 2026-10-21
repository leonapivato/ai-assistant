# Vision

## A Personal AI That Becomes More Useful the Longer You Use It

The goal of this project is to build **Aether**: a deeply personalized, model-agnostic AI assistant that helps people manage everyday life across conversations, tools, projects, routines, and decisions, first for one person and then for the household they share.

It should not feel like a chatbot that starts over with every request. It should feel like a persistent personal intelligence layer: one that understands the user, remembers what matters, coordinates the right models and tools, and gradually learns how to be more helpful.

The core product is not the underlying language model. Models will continue to improve, change, and become interchangeable. The lasting value of this system is the orchestration layer around them: the user model, memory system, context engine, permissions, integrations, planning, and learning loops that turn general-purpose AI into a trusted personal assistant.

---

## The Problem

Today's AI assistants are powerful but fragmented.

They can write, summarize, reason, search, and use tools, but they still have limited continuity across the user's life. They often:

- forget important context;
- treat each conversation as an isolated interaction;
- store shallow or unreliable memories;
- lack awareness of active goals and commitments;
- require the user to repeatedly explain preferences;
- operate across disconnected applications;
- provide generic answers instead of personalized decisions;
- wait for instructions rather than offering timely help;
- take actions without a sufficiently clear model of trust, permissions, or consequences.

The result is an assistant that may be intelligent in the moment but does not yet feel truly personal.

A useful everyday assistant must do more than answer questions. It must understand the individual, maintain continuity, act across tools, recognize context, and earn greater responsibility over time.

---

## Product Vision

This project will serve as a user-facing interface and orchestration layer for AI models.

It will combine:

- interchangeable AI models;
- a persistent user model;
- typed long-term memory;
- active goals, projects, and commitments;
- real-time situational context;
- planning and execution systems;
- integrations with everyday tools;
- permissions and approval policies;
- continuous learning from user feedback.

The assistant should become increasingly valuable as it accumulates accurate, user-controlled context.

Over time, it should move from:

> “What would a typical user want?”

to:

> “What would this user want, in this situation, given their goals, preferences, history, and current context?”

The system should eventually help with communication, scheduling, planning, research, reminders, task execution, decision support, personal organization, and device or service coordination through one consistent interface.

The assistant is separate from the interfaces it is reached through. It lives behind all of them and reasons across them. A person can start a thought by text on one platform and finish it on another, someone else in the household can talk to it at the same time, and meanwhile it can be working on something long, such as a job search or research, and come back when there is something worth saying. An interface is how the assistant is reached. The assistant itself is one continuous intelligence behind every interface.

---

## Who It Serves

**A person first.** The first assistant serves one person. It learns them, works for them and answers to them.

**Then a household.** One assistant can serve a household. It recognizes who is speaking and how they are interacting, and what it shares, what it may do and how it speaks change with the person. One person, the owner, has the final say. Members and permission groups come later; until they are designed, the owner holds complete control. Whatever the arrangement, the assistant is honest with each person about who can see what.

**Each household is its own.** One household's data never mixes with another's. People can run their own hub, or have one run for them.

---

## The User Promise

The assistant should make the user feel:

### Understood

It remembers relevant preferences, goals, relationships, routines, projects, and past decisions without forcing the user to repeat themselves.

### Supported

It reduces cognitive load by organizing information, tracking commitments, anticipating reasonable next steps, and coordinating tools.

### In Control

It does not confuse personalization with unrestricted autonomy. The user can inspect, correct, approve, restrict, export, or delete what the assistant knows and does.

### More Capable Over Time

Each useful interaction should improve future assistance. Corrections, choices, and repeated behaviors should become learning signals rather than disappearing after the conversation ends.

### Free to Choose Models

The user's personal context should not be trapped inside one model provider. The orchestration layer should be able to route work across multiple models without losing the assistant's identity or understanding of the user. As open models become competitive, it should be able to run entirely on hardware the user owns.

---

## Core Principles

### 1. Personalization Is the Product

Personalization must go beyond storing facts.

The system should develop a structured, evolving model of the user's:

- goals;
- preferences;
- routines;
- communication style;
- relationships;
- projects;
- decision patterns;
- constraints;
- recurring responsibilities;
- preferred workflows.

Every inference should have evidence, confidence, scope, and a way to be corrected.

That model should be built chiefly by **observation**, not by interrogation. An
assistant that learns only what it is explicitly told reproduces the failure this
project exists to remove: the user explaining themselves over and over. So the
system should form beliefs from what it sees — the interactions it takes part in,
and, where the user grants them, read-only sources it may ingest. Observation
matters most at the beginning, when nothing has been asserted yet and the
assistant would otherwise have nothing to work from.

Explicit correction is the steering wheel rather than the engine. What the user
states outranks what the assistant inferred, and stating something is how the
user takes a belief back. Observation supplies the volume; correction supplies
the direction.

### 2. Memory Must Be Typed and Intentional

Memory should not be one undifferentiated vector database.

Long-term memory is organized into typed kinds:

- episodic memories (what happened);
- semantic memories (durable facts);
- learned preferences;
- procedures and preferred workflows.

Stable profile information is not a separate store but a matter of provenance: facts the user asserted directly, held with full confidence, versus beliefs the assistant inferred with lower confidence. Some state often mistaken for memory lives in adjacent subsystems instead — active projects and commitments in planning, and temporary situational context in the context engine.

The assistant should remember selectively, detect conflicts, update stale information, and avoid preserving sensitive or incidental details without justification.

Selective here means selective about what becomes lasting knowledge and what is brought up, not about what is heard. Everything the user tells the assistant stays in the record of what happened. What becomes lasting knowledge about them passes a worth-keeping test and carries its evidence. Beyond that, selectivity lives in what is surfaced and in what is forgotten. Input the assistant only overhears or senses meets a higher bar than what a person says to it.

Observing broadly and retaining broadly are different things, and the distance
between them is where this principle does its work. What the assistant observes
is *proposed*; a deterministic policy decides what is kept; and what is kept
carries its provenance, its confidence, and the evidence behind it. The user can
read the resulting beliefs, see why each is held, correct any of them, and delete
any of them. Watching is trustworthy only on those terms — a system that observes
with no gate in front of memory and no inspection surface behind it is
surveillance, not personalization.

### 3. Trust Must Be Built Into the Architecture

Trust cannot depend only on a prompt telling the model to be careful.

The orchestration layer should explicitly define:

- which tools are available;
- what data each tool can access;
- which actions require approval;
- which actions are reversible;
- spending or communication limits;
- audit history;
- explanations for consequential decisions;
- clear recovery from mistakes.

Low-risk, reversible actions may become more automatic. High-impact actions should remain inspectable and permissioned.

Reading the world and acting on it are governed separately. A **reader** — a
read-only source the user has connected, feeding situational context and
observation — is granted, scoped, and revocable, but it changes nothing outside
the assistant. An **actuator** — a tool that sends, buys, schedules, or modifies —
carries consequences that may be irreversible, and answers to the approval,
limit, and audit machinery above. Collapsing the two into one notion of
"integration" would either over-restrict reading or under-restrict acting.

The privacy that matters most is privacy toward people. An assistant that lives in
a home must not repeat one person's things to someone who should not hear them: a
roommate, a guest, whoever is in the room. Disclosure to a service the user chose
is a different question, governed by grants and destinations rather than by
audience.

The test for how it handles people is what a trusted human assistant or companion
would do. Such a person knows what they need to know and is careful with it. They
deflect a nosy question naturally, keep other people's confidences, stay discreet
when they can't tell who is listening, and say plainly whom they work for. The
assistant behaves the same way, by judgment rather than by a rule for every case.
Where it differs from a person, judgment alone is not enough:

- it remembers everything, word for word, so what is kept and what forgetting means
  are explicit rules;
- it often cannot see who is present, so when it cannot tell, it acts as a discreet
  person would who doesn't know who is listening;
- it is easier to manipulate than a person, so a few things are hard rules in code:
  secrets are never said, nothing it reads can make it act without the user's yes,
  and someone else claiming the user's permission is not permission;
- its judgment can shift when its model changes, so the cases that matter are
  tested.

### 4. Context Determines Usefulness

The most intelligent answer is not always the most useful answer.

The system should account for relevant context such as:

- time;
- location when permitted;
- device;
- calendar state;
- deadlines;
- active tasks;
- recent interactions;
- user attention;
- urgency;
- current goals.

Context should influence what information is retrieved, how much is presented, when the user is interrupted, and whether the assistant should act at all.

### 5. Proactivity Must Earn Its Place

The assistant should not be passive forever, but it should also not become noisy.

Proactive suggestions should be evaluated according to:

- expected usefulness;
- urgency;
- confidence;
- interruption cost;
- relevance to an active goal;
- whether the opportunity will expire.

The assistant should learn when the user welcomes intervention and when silence is better.

How much it does unasked, and when it speaks first, are boundaries set per person, the way a human assistant works them out with the person they work for. Some the person states, such as "book restaurants under $50 without asking" or "don't message me before nine". Others the assistant proposes after seeing a pattern, and the person accepts or declines. Each boundary is visible and changeable, and deterministic code enforces it, so the model can never widen its own limits. Someone new starts careful: the assistant asks before anything leaves their hub, and stays quiet unless asked.

Proactivity also means working while the user is away. A search or a task that takes days continues in the background, survives restarts, and reports back when there is something worth saying.

### 6. Models Are Components, Not the Product

The system should route requests based on capability, speed, cost, privacy, and reliability.

Different models may be better suited for:

- fast conversational responses;
- long-form reasoning;
- coding;
- vision;
- local or private processing;
- structured extraction;
- planning;
- verification.

The user experience and personal context should remain consistent even when the underlying model changes.

### 7. Deterministic Systems Own Critical State

Language models may propose plans, interpret information, and generate language, but deterministic services should control:

- permissions;
- identity;
- scheduling;
- state transitions;
- transaction limits;
- retries;
- audit logs;
- confirmations;
- deletion;
- execution status.

The system should use probabilistic intelligence without making critical state probabilistic.

### 8. The Assistant Is a Resident Service, Not an Application

The assistant should exist between interactions, not only during them.

One resident service — the hub — should own the state and the intelligence:
memory, the user model, conversations, plans, permissions, and the work that
happens while nobody is watching. Every interface should be a **stateless
client** of that service. A conversation begun in one place should be resumable
in another, because the conversation lives in the hub rather than in whatever
displayed it.

Several of the promises above depend on this shape. Proactivity needs something
awake to notice. Continuity needs identity and context to belong to the user
rather than to a device. And keeping critical state deterministic (Principle 7)
is far easier when exactly one process owns it.

Living behind every interface also means doing more than one thing at once. Two
people may be talking to it, or one person on two devices, while long-running work
continues. Each has its own context, and none blocks the others.

### 9. It Feels Human, and Never Pretends to Be

Interaction should feel natural and human, with a personality each person can
adjust. The assistant reads which moments call for which tone, depending on the
person and the context: calm and brief under stress, warm for good news, short
while someone is driving.

Underneath, its character is stable: honest, warm and competent. A style or a
personality changes how it speaks, never what is true or what it judges best. It
never claims to be human or to feel what it does not.

### 10. Built for the Models That Are Coming

Models will become cheaper and open models more capable. Compatibility with other
products will become easier as AI makes reverse engineering cheap. The system
should be ready for all three:

- it should be able to run entirely on hardware the user owns, including the hub,
  the models and speech, and each stage should be checked on a model before it
  moves to it;
- it should be designed for far more model calls than today's prices encourage,
  while keeping cost discipline in the present;
- integrations should use standards and broad bridges first, and keep narrow or
  reverse-engineered integrations behind adapters, so that a change upstream breaks
  one adapter rather than the assistant.

---

## Core System Capabilities

These are the capabilities the system is being built to have. They describe the
target, not what is implemented; what has actually landed is recorded in
`docs/adr/` and the commit log, not here.

### Persistent User Model

A structured representation of what is known or inferred about the user, including confidence, evidence, context, and recency.

### People and Households

Knowing who is speaking and how sure it is, and keeping a model of each person: their profile, the style they prefer, and their boundaries. A household is a set of members under an owner who has the final say.

### Memory System

Storage and retrieval across profile facts, preferences, episodes, and procedures.

### Context Engine

Assembly of the smallest relevant set of current and historical information needed for the task.

### Goal and Project Management

Persistent representations of long-term objectives, milestones, unresolved questions, dependencies, and progress.

### Planning and Execution

The ability to decompose requests into steps, choose tools, request approval when needed, recover from errors, and resume interrupted work.

### Background Work

Long-running tasks that continue while the user is away, survive restarts, and report back when there is something worth saying.

### Tool and Integration Layer

A consistent interface to services such as email, calendar, notes, messaging, files, task systems, smart devices, health platforms, vehicles, and future integrations. Read-only sources, which feed context and observation, are governed separately from tools that act on the world (Principle 3), even where both reach the same service.

### Everyday Presence

The assistant reaches into everyday life through spokes: the computer, phone, watch, household devices, TVs, speakers, the car, and household sensing such as Wi-Fi presence. Each is attached with consent, one signal at a time. A shared surface depends on knowing who is present.

### Permission and Autonomy System

Explicit policies governing what the assistant may read, suggest, draft, modify, send, purchase, schedule, or control.

### Feedback and Learning Loop

A system for converting corrections, edits, ignored suggestions, repeated choices, and explicit ratings into carefully scoped improvements. Its primary input is observation — the interactions the assistant takes part in, and the read-only sources the user has connected — with explicit correction as the signal that outranks everything else.

### Proactive Assistance

Triggers and policies that identify useful moments to remind, recommend, prepare, or act.

### Observability and Evaluation

Traces that make it possible to understand what context was used, why a decision was made, what tools were called, and whether the result helped.

### A Living Presence

A visible form in the user's interfaces that is a view of what the assistant knows and of what the hub is actually doing. It should be beautiful enough to want to look at, and never show anything that isn't happening.

---

## High-Level Architecture

```text
Spokes: phone, web, Telegram, computer, speakers, sensors, timers
          |
          v
Channels: what came in, where, from whom, and who can hear
          |
          v
The hub: one per household, always on
  - Recall: what it already knows that bears on this
  - Understanding: what the input means and who it involves
  - Planning: what to say and do, in rounds
  - Authorizing: rules, boundaries and approvals, decided by code
  - Acting: tools and messages, each recorded
          |
          v
The episode: what came in, what was understood, what was done
          |
          v
Learning: what is worth remembering, kept with its evidence
```

---

## The Long-Term Moat

The defensible value of the product is the accumulated understanding of the individual user.

A general model can answer a question intelligently. A mature personal assistant should also know:

- why the user is asking;
- how the answer relates to an active goal;
- what tradeoffs the user normally prefers;
- what has already been tried;
- which people, tools, or commitments are involved;
- whether now is the right time to act;
- how much autonomy the user has granted.

This creates a compounding advantage: the assistant becomes harder to replace because its usefulness comes from a long history of accurate, user-controlled learning.

A key long-term artifact may be a portable personal context graph that represents the user's goals, preferences, projects, relationships, routines, and history independently of any specific AI provider.

---

## Initial Product Scope

The first version should not attempt to control every aspect of a user's life.

It should prove one complete personalization loop:

1. The user interacts naturally.
2. The system identifies potentially useful context.
3. Relevant memories and preferences are retrieved.
4. The assistant produces a personalized response or plan.
5. The user corrects, accepts, rejects, or edits the result.
6. The system proposes a scoped learning update.
7. The updated preference improves a later interaction.

The first version is reached through messaging and includes:

- a chat on the web and on Telegram;
- typed long-term memory, learned from conversation and kept with its evidence;
- a profile of each person;
- research on the web, and email with approval;
- draft-first actions and approval workflows;
- inspection and correction of what it knows;
- model routing;
- a small invite-only pilot with friends and family, hosted for them.

This is more valuable than launching with dozens of shallow integrations.

---

## Non-Goals

At least initially, the project is not intended to:

- train a frontier foundation model;
- replace every application with a single interface;
- take consequential actions without user-defined authorization;
- infer or retain unlimited personal information;
- simulate consciousness or claim human-like awareness;
- maximize engagement through excessive notifications;
- automate tasks merely because automation is technically possible;
- lock the user's data to one model vendor.

The limit on inference and retention bounds the observation principle
(Principle 1) rather than contradicting it. The assistant should watch in order
to learn; what it keeps is what passes the memory gate, carries its evidence, and
can be inspected, corrected, and deleted. Broad observation is not a licence for
broad retention.

The objective is dependable assistance, not artificial omniscience.

---

## Measures of Success

The project should be evaluated by whether it improves the user's life, not by how agentic it appears.

Important measures include:

- percentage of tasks completed successfully;
- reduction in repeated explanations;
- memory precision and correction rate;
- preference prediction accuracy;
- rate of accepted versus dismissed suggestions;
- frequency of user overrides;
- number of unnecessary clarification questions;
- time saved;
- completion of long-running goals;
- trust in higher-autonomy actions;
- user understanding of why actions occurred;
- retention driven by usefulness rather than novelty.

A strong signal of success is when the user begins to rely on the assistant because it consistently understands context that generic AI systems miss.

---

## Major Risks

### Incorrect Personalization

The system may overgeneralize from limited evidence or preserve outdated assumptions.

**Response:** confidence scores, evidence tracking, contextual preferences, expiration, conflict detection, and easy correction.

### Privacy and Security

The assistant may gain access to highly sensitive services and data.

**Response:** least-privilege access, owner-only file permissions with an OS full-disk-encryption baseline and opt-in application-level encryption, explicit scopes, local processing where useful, auditability, and user-controlled deletion.

### Excessive Autonomy

The system may act when it should ask.

**Response:** risk tiers, approval policies, reversibility checks, and gradual autonomy earned through user consent.

### Notification Fatigue

Proactivity may become interruption.

**Response:** interruption-cost modeling, quiet periods, relevance thresholds, and feedback-based adaptation.

### Household Trust

In a shared home, one person's things may reach another.

**Response:** knowing who is speaking and who is present, saying plainly what the owner can see, and designing members and permission groups before the assistant is shared.

### Model Unreliability

Underlying models may hallucinate, misinterpret tool results, or create unstable plans.

**Response:** structured outputs, validation, deterministic state control, verification steps, and model-specific routing.

### Product Scope

The vision can easily expand into an unbuildable system.

**Response:** focus on narrow, complete workflows and deepen personalization before expanding breadth.

---

## North Star

The project succeeds when the assistant is not merely impressive during a demonstration, but quietly dependable in everyday life.

It should become a trusted layer between the user and their digital world: capable of understanding what matters, coordinating the right intelligence and tools, and helping the user follow through.

The long-term vision is:

> A personal AI system that understands the individual, grows with them, acts according to their values and permissions, and remains useful regardless of which underlying model is best.

---

## Related documents

This document is the canonical statement of *why* and *what*. It is aspirational
and changes rarely.

- **How and in what order** we build it — `docs/roadmap.md`.
- **Decisions that commit us** to specifics — `docs/adr/`. Where this vision and
  a ratified ADR disagree, the ADR wins.
- **What has actually landed** — `docs/adr/` for the decisions, the commit log
  for the code. There is no changelog (ADR-0067).
