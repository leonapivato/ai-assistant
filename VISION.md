# Vision

## A Personal AI That Becomes More Useful the Longer You Use It

The goal of this project is to build a deeply personalized, model-agnostic AI assistant that helps people manage everyday life across conversations, tools, projects, routines, and decisions.

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

The user's personal context should not be trapped inside one model provider. The orchestration layer should be able to route work across multiple models without losing the assistant's identity or understanding of the user.

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

### 2. Memory Must Be Typed and Intentional

Memory should not be one undifferentiated vector database.

Long-term memory is organized into typed kinds:

- episodic memories (what happened);
- semantic memories (durable facts);
- learned preferences;
- procedures and preferred workflows.

Stable profile information is not a separate store but a matter of provenance: facts the user asserted directly, held with full confidence, versus beliefs the assistant inferred with lower confidence. Some state often mistaken for memory lives in adjacent subsystems instead — active projects and commitments in planning, and temporary situational context in the context engine.

The assistant should remember selectively, detect conflicts, update stale information, and avoid preserving sensitive or incidental details without justification.

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

---

## Core System Capabilities

### Persistent User Model

A structured representation of what is known or inferred about the user, including confidence, evidence, context, and recency.

### Memory System

Storage and retrieval across profile facts, preferences, episodes, procedures, projects, and commitments.

### Context Engine

Assembly of the smallest relevant set of current and historical information needed for the task.

### Goal and Project Management

Persistent representations of long-term objectives, milestones, unresolved questions, dependencies, and progress.

### Planning and Execution

The ability to decompose requests into steps, choose tools, request approval when needed, recover from errors, and resume interrupted work.

### Tool and Integration Layer

A consistent interface to services such as email, calendar, notes, messaging, files, task systems, smart devices, health platforms, vehicles, and future integrations.

### Permission and Autonomy System

Explicit policies governing what the assistant may read, suggest, draft, modify, send, purchase, schedule, or control.

### Feedback and Learning Loop

A system for converting corrections, edits, ignored suggestions, repeated choices, and explicit ratings into carefully scoped improvements.

### Proactive Assistance

Triggers and policies that identify useful moments to remind, recommend, prepare, or act.

### Observability and Evaluation

Traces that make it possible to understand what context was used, why a decision was made, what tools were called, and whether the result helped.

---

## High-Level Architecture

```text
User or External Trigger
          |
          v
Intent, Risk, and Task Classification
          |
          v
Context Assembly
  - Current situation
  - Relevant memories
  - Active goals and projects
  - Commitments
          |
          v
Planner and Model Router
  - Select model
  - Construct plan
  - Select tools
  - Identify approval points
          |
          v
Permission and Policy Check
          |
          v
Execution Engine
  - Tool calls
  - State tracking
  - Retries
  - Validation
          |
          v
Response, Action, or Notification
          |
          v
Feedback Capture
          |
          v
Memory and User-Model Update Proposal
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

A focused initial product could include:

- conversational interface;
- user profile and preference management;
- typed long-term memory;
- goals and active projects;
- calendar and email integrations;
- draft-first actions;
- approval workflows;
- feedback capture;
- model routing;
- audit and memory inspection.

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
- **What has shipped** — `CHANGELOG.md`. (The memory subsystem — typed memory,
  the propose/dispose write path, and a persistent semantic store — is built.)
