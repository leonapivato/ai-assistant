# The assistant's end of a channel

**The question.** What makes something a sensor or an actuator, and therefore what is
a device that reaches a channel; and which directions may a channel kind carry?

This is a general change to the channel model, between ADR-0290 (what a channel is
and where one is needed) and the conversation channel
([#2680](https://github.com/leonapivato/ai-assistant/pull/2680)), which applies it to
one kind. It came out of reviewing the conversation channel with the owner on
2026-10-04: two questions raised there turned out to be about every channel, not the
conversation, so they are settled here first, as ADR-0291 was.

## Baseline

Wiki pages, read at wiki revision
[`b95617b`](https://github.com/leonapivato/ai-assistant/wiki/Channels/b95617b24abc2f1bbef5997ecf4b36eb6056bbc6):
[Channels](https://github.com/leonapivato/ai-assistant/wiki/Channels),
[Sensors](https://github.com/leonapivato/ai-assistant/wiki/Sensors),
[External sensors](https://github.com/leonapivato/ai-assistant/wiki/External-sensors) and
[Actuators](https://github.com/leonapivato/ai-assistant/wiki/Actuators).

They, and ADR-0290 §3 and §4, place sensors and actuators by where they run: inside
the hub, or on a device outside it. ADR-0290 §4's prose then counts a device that
shows a reply as an external actuator: *"An external actuator is on a device and
shows or says what it is given."* The Actuators page does the same: a reply's
actuator is *"External, on the spoke that shows or says it"*. Nothing says which
directions a channel kind carries.

| ADR | What it decides today | What this proposal would do |
| --- | --- | --- |
| ADR-0290 §1:3, §1:7 | Every channel has a kind, an identity, and what its kind declares; a kind declares a description and requirements. | Amend: a kind also declares its directions (§3) and, where it is a shared medium, that its devices are parties' ends (§2). |
| ADR-0290 §3, §4 | A sensor brings new input onto a channel and an actuator carries output from one; external ones run on a device, internal ones in the hub. Its §4 prose counts a device that shows output as an external actuator. | Kept, with one correction to the §4 prose: a device showing a shared medium to its party is not an actuator (§2). No normative clause is superseded. |
| ADR-0291 §1–§3 | A channel is a medium tied to neither end; its record is its own; what it keeps is its kind's choice. | Kept. |
| ADR-0094 §1 | "Client", "sensor" and "actuator" are profile names for a spoke: *"a client carries a person, a sensor reads the world, an actuator acts on it"*. No rule may be conditioned on them. | Kept, and it now lines up: a party's end of a shared medium is what ADR-0094 calls a client, and the assistant's organ on a device is what it calls a sensor or an actuator. No rule here is conditioned on a spoke's profile name; what decides is the channel kind's declaration. |

## The change

### 1. A sensor or actuator is the assistant's own end of a medium

A **sensor** is where the assistant perceives a medium, and an **actuator** is where it
acts or speaks into one. Each sits wherever the assistant meets that medium, so it can
run in the hub or on a device, as ADR-0290 §3 and §4 already say.

| Medium | The assistant's end | Where it runs | The other side |
| --- | --- | --- | --- |
| A conversation | Reading the chat; writing into it | Hub | The user, on their devices |
| A timer | Noticing a moment has come | Hub | The clock |
| A search or email service | Making the call; taking the answer | Hub | The provider |
| A camera or microphone | The device, as the assistant's eye or ear | Device | The room |
| A room speaker | The device, as the assistant's mouth | Device | Whoever is in the room |
| A desktop spoke ([#1595](https://github.com/leonapivato/ai-assistant/issues/1595)) | The device, as the assistant's hand and eye | Device | The user's computer |

### 2. A device is the assistant's organ, or a party's end of a shared medium

A device that reaches a channel is one of two things, and the channel's kind says
which:

- **The assistant's organ**: a sensor or an actuator on a device. The camera is the
  assistant's eye, the speaker its mouth. What the speaker says is the assistant's
  output, and whoever is in range perceives it.
- **A party's end of a shared medium**: a medium the hub holds, which both the
  assistant and another party read and write. A conversation is one. The user's phone
  is the user's end of it: the user writes from it and reads on it. It is not the
  assistant's sensor or actuator, as the other person's phone is not part of you when
  you text them.

The difference matters in three places:

- **Output.** The assistant's actuator on a shared medium writes into the medium.
  What a party's device then shows is that party reading the medium, not a further
  output of the assistant's.
- **Audience.** On an organ, the audience is whoever perceives it: a room speaker's is
  unbounded (ADR-0199 §1). On a shared medium, it is whoever holds an end of it, which
  the kind's own rules decide; for the conversation, the user chooses which devices
  are theirs on it.
- **Recording.** A shared medium held by the hub is its own record: the chat is what
  both ends read (ADR-0291 §2, §3).

### 3. A kind declares its directions, exactly

> A channel kind declares exactly one of: **in only**, **out only**, or **both**.
> Every instance of the kind carries what the kind declares, and no instance varies it.

- **No "any".** A direction that varied by instance would make every rule and every
  planning question about a channel ("can I send here?") depend on which instance it
  is, against ADR-0290 §1:2's "every channel of one kind follows the same rules".
- **Declaring a direction does not oblige using it.** A conversation carries both, and
  one nobody ever types into is still a conversation. A kind declares the most it can
  carry.
- **Where two instances really differ in direction, they are two kinds.** An
  integration whose directions are not known in advance registers as its own kind
  with its own declaration, rather than one catch-all kind.
- **Permission is not direction.** A connected inbox with read-only access is still of
  a kind that carries out; authorizing refuses the send because nothing was granted.
  What a channel can carry is its kind's; what the assistant may do on it is
  authority's.

A party's device on a shared medium may use one direction or both: a phone may write
into a conversation and read it, a watch may only read it. That is the party's choice
within the kind's directions.

## Options considered

**Every device that shows or says output is an external actuator** (ADR-0290 §4's
prose, and the wiki). Declined: it makes the user's own phone the assistant's organ,
so who sees a conversation would be a fact about the assistant's outputs rather than
about who is in the conversation.

**Sensors and actuators always run in the hub, with every device a far end** (this
proposal's first draft). One place for everything that applies a kind's rules.
Declined (owner, 2026-10-04): a camera really is the assistant's eye and a speaker its
mouth, and calling them far ends hides that their audience is whoever is in range.

**A direction of "any", decided per instance.** Declined (§3): it moves the shape of a
channel from its kind to its instance.

## What it leaves open

- **Whether a conversation and its channel are one thing.** For the hub's own chat
  they coincide; whether a conversation is a concept above channels is the
  conversation channel's question.
- **Shared media the hub does not hold**, such as an email thread or a messaging app
  group: the assistant's end is in the hub, and the medium is elsewhere. How such a
  channel is modelled is each kind's.
- **Readers' channel**, still open from ADR-0290.
