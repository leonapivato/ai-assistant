# Third-party notices

This distribution contains third-party material in addition to this project's
own source code. This project's code is licensed under the MIT Licence; see the
root `LICENSE` file, which covers **only** this project and nothing recorded
here.

This file exists because the wheel and the sdist **redistribute** pre-trained
models: an embedding model (ADR-0024) and, since ADR-0200, the two speech models
the transcription and synthesis seams run on. It records what each artifact is,
where it came from, and the licence each upstream source claims for it, and it
reproduces the full text of every licence claimed.

There are three artifacts. Each is packaged under
`ai_assistant/models/_vendor/<directory>/`, and the SHA-256 of every file as
shipped is recorded in this project's source and verified at build time.

# 1. The embedding model

## What is redistributed

| | |
|---|---|
| Model | `BAAI/bge-small-en-v1.5` |
| Artifact source repository | `Qdrant/bge-small-en-v1.5-onnx-Q` (`https://huggingface.co/Qdrant/bge-small-en-v1.5-onnx-Q`) |
| Pinned commit | `52398278842ec682c6f32300af41344b1c0b0bb2` |
| Files | `config.json`, `model_optimized.onnx`, `special_tokens_map.json`, `tokenizer.json`, `tokenizer_config.json` |

Those five files are the whole of the redistributed artifact. They are packaged
under `ai_assistant/models/_vendor/bge-small-en-v1.5/`. The SHA-256 of each file
as shipped is recorded in `src/ai_assistant/models/embedding_artifact.py`
(`ARTIFACT_MANIFEST`) and is verified at build time.

`fastembed` refers to the same source repository in lower case
(`qdrant/bge-small-en-v1.5-onnx-q`); Hugging Face repository names are
case-insensitive and both forms resolve to the repository named above.

### Statement of changes

The five files are redistributed **verbatim and unmodified** — byte for byte as
published at the pinned commit, which is what the recorded SHA-256 of each file
asserts. Nothing is retrained, re-quantised, re-exported, converted, stripped or
otherwise altered. This statement is made because the Apache License 2.0 §4(b)
requires modified files to carry prominent notices of modification, and there
are no modifications.

## The two upstream works, and the licence each source claims

There are two works in this artifact's provenance: the original model weights,
and the ONNX export and quantisation derived from them. The claims recorded
below are what each source states, transcribed without adjudication. Both
licence texts are reproduced in full further down, so this distribution carries
the notice required by either.

### 1. Original model — `BAAI/bge-small-en-v1.5`

- Project: BGE / FlagEmbedding, by the Beijing Academy of Artificial
  Intelligence (BAAI).
- Source: `https://huggingface.co/BAAI/bge-small-en-v1.5`
- Licence claimed: **MIT**. The model repository's card metadata declares
  `license: mit`, and the card's "License" section states: "FlagEmbedding is
  licensed under the [MIT License](https://github.com/FlagOpen/FlagEmbedding/blob/master/LICENSE).
  The released models can be used for commercial purposes free of charge."
- Copyright holder: **the model repository states none.** It carries no
  `LICENSE` file. The MIT text its card links to lives in the FlagEmbedding
  source repository (`https://github.com/FlagOpen/FlagEmbedding`) and carries
  the copyright line `Copyright (c) 2022 staoxiao`; that text is reproduced
  below exactly as published there. No copyright line has been composed for the
  weights themselves.

### 2. ONNX export and quantisation — `Qdrant/bge-small-en-v1.5-onnx-Q`

- Project: Qdrant.
- Source: `https://huggingface.co/Qdrant/bge-small-en-v1.5-onnx-Q`
- Licence claimed: **Apache-2.0**. The repository's card metadata declares
  `license: apache-2.0`. The card describes the repository as a "Quantized ONNX
  port of BAAI/bge-small-en-v1.5".
- Copyright holder: **the repository states none.** At the pinned commit it
  contains no `LICENSE` file, no `NOTICE` file, and no copyright line — so no
  NOTICE-file contents are reproducible under Apache License 2.0 §4(d), and no
  copyright line has been composed for it. Attribution is to the Qdrant project
  as the publisher of that repository.

### Also recorded

`fastembed`, the library through which this artifact is loaded, records
`license='mit'` for `BAAI/bge-small-en-v1.5` in its own model metadata
(`DenseModelDescription`, version 0.8.0).

---

# 2. The speech-recognition model

## What is redistributed

| | |
|---|---|
| Model | Moonshine tiny (English), int8-quantised |
| Artifact source repository | `csukuangfj/sherpa-onnx-moonshine-tiny-en-int8` (`https://huggingface.co/csukuangfj/sherpa-onnx-moonshine-tiny-en-int8`) |
| Pinned commit | `bf2b762c076d8ea61e2af0b3851c9564fb77552e` |
| Files | `preprocess.onnx`, `encode.int8.onnx`, `uncached_decode.int8.onnx`, `cached_decode.int8.onnx`, `tokens.txt` |

Those five files are the whole of the redistributed artifact. They are packaged
under `ai_assistant/models/_vendor/moonshine-tiny-en-int8/`. The SHA-256 of each
file as shipped is recorded in `src/ai_assistant/models/speech_artifact.py`
(`MOONSHINE_TINY_EN_INT8`) and is verified at build time.

### Statement of changes

The five files are redistributed **verbatim and unmodified** — byte for byte as
published at the pinned commit, which is what the recorded SHA-256 of each file
asserts. Nothing is retrained, re-quantised, re-exported, converted, stripped or
otherwise altered. The source repository holds other files this distribution does
**not** ship (its `README.md`, its `LICENSE`, and sample recordings under
`test_wavs/`); shipping a subset is not a modification of the files shipped, and
the licence text its `LICENSE` carries is reproduced in full below.

## The upstream work, and the licence the source claims

- Project: Moonshine, by Useful Sensors
  (`https://github.com/usefulsensors/moonshine`). The source repository above is
  a conversion of that model to the four-file ONNX layout `sherpa-onnx` loads.
- Source: `https://huggingface.co/csukuangfj/sherpa-onnx-moonshine-tiny-en-int8`
- Licence claimed: **MIT**. At the pinned commit the repository carries a
  `LICENSE` file whose text is the MIT Licence with the copyright line
  `Copyright (c) 2024 Useful Sensors`. Its card metadata declares no licence
  field, so the `LICENSE` file is the claim, transcribed here without
  adjudication.
- Copyright holder: **Useful Sensors**, per that file's own copyright line.
- The conversion itself: the repository states no separate licence for the ONNX
  export and no second copyright line, so no claim has been composed for it.
  Attribution for the conversion is to the repository's publisher.

---

# 3. The speech-synthesis model

## What is redistributed

| | |
|---|---|
| Model | Supertonic 3 (text-to-speech), int8-quantised |
| Artifact source repository | `csukuangfj2/sherpa-onnx-supertonic-3-tts-int8-2026-05-11` (`https://huggingface.co/csukuangfj2/sherpa-onnx-supertonic-3-tts-int8-2026-05-11`) |
| Pinned commit | `cca5a0e6c96e1d2c720986bf7e75fcc81dee3ae4` |
| Files | `LICENSE`, `duration_predictor.int8.onnx`, `text_encoder.int8.onnx`, `vector_estimator.int8.onnx`, `vocoder.int8.onnx`, `tts.json`, `unicode_indexer.bin`, `voice.bin` |

Those eight files are the whole of the redistributed artifact. They are packaged
under `ai_assistant/models/_vendor/supertonic-3-int8/`. The SHA-256 of each file
as shipped is recorded in `src/ai_assistant/models/speech_artifact.py`
(`SUPERTONIC_3_INT8`) and is verified at build time.

**The upstream `LICENSE` file is one of the eight**, deliberately: the MIT Licence
requires its notice to travel with the material, and shipping the file beside the
weights is the most direct way to do that. Its text is also reproduced below.

### Statement of changes

The eight files are redistributed **verbatim and unmodified** — byte for byte as
published at the pinned commit. Nothing is retrained, re-quantised, re-exported,
converted, stripped or otherwise altered. The source repository holds one file
this distribution does not ship, its `README.md`.

## The upstream work, and the licence the source claims

- Project: Supertonic, by Supertone Inc.
  (`https://github.com/supertone-inc/supertonic`).
- Source: `https://huggingface.co/csukuangfj2/sherpa-onnx-supertonic-3-tts-int8-2026-05-11`
- Licence claimed: **MIT**. The repository carries a `LICENSE` file whose text is
  the MIT Licence with the copyright line `Copyright (c) 2025 Supertone Inc.`.
  Its card metadata declares no licence field, so that file is the claim.
- Copyright holder: **Supertone Inc.**, per that file's own copyright line.
- The int8 quantisation: the repository states no separate licence for it and no
  second copyright line, so no claim has been composed for it.

### What is deliberately **not** redistributed

An earlier candidate for this seam was a Piper VITS voice, whose
grapheme-to-phoneme pass reads an **espeak-ng data directory** — several hundred
files derived from a **GPL-3.0** project. It was rejected, and no espeak-ng
material is packaged in this distribution. The model above is indexed directly off
the characters it is handed and needs no pronunciation data at all.

---

## MIT License

Reproduced from the FlagEmbedding repository
(`https://github.com/FlagOpen/FlagEmbedding/blob/master/LICENSE`), the text the
`BAAI/bge-small-en-v1.5` model card links as its licence.

```text
MIT License

Copyright (c) 2022 staoxiao

Permission is hereby granted, free of charge, to any person obtaining a copy
of this software and associated documentation files (the "Software"), to deal
in the Software without restriction, including without limitation the rights
to use, copy, modify, merge, publish, distribute, sublicense, and/or sell
copies of the Software, and to permit persons to whom the Software is
furnished to do so, subject to the following conditions:

The above copyright notice and this permission notice shall be included in all
copies or substantial portions of the Software.

THE SOFTWARE IS PROVIDED "AS IS", WITHOUT WARRANTY OF ANY KIND, EXPRESS OR
IMPLIED, INCLUDING BUT NOT LIMITED TO THE WARRANTIES OF MERCHANTABILITY,
FITNESS FOR A PARTICULAR PURPOSE AND NONINFRINGEMENT. IN NO EVENT SHALL THE
AUTHORS OR COPYRIGHT HOLDERS BE LIABLE FOR ANY CLAIM, DAMAGES OR OTHER
LIABILITY, WHETHER IN AN ACTION OF CONTRACT, TORT OR OTHERWISE, ARISING FROM,
OUT OF OR IN CONNECTION WITH THE SOFTWARE OR THE USE OR OTHER DEALINGS IN THE
SOFTWARE.
```

---

## Apache License 2.0

Reproduced verbatim from `https://www.apache.org/licenses/LICENSE-2.0.txt`.

```text

                                 Apache License
                           Version 2.0, January 2004
                        http://www.apache.org/licenses/

   TERMS AND CONDITIONS FOR USE, REPRODUCTION, AND DISTRIBUTION

   1. Definitions.

      "License" shall mean the terms and conditions for use, reproduction,
      and distribution as defined by Sections 1 through 9 of this document.

      "Licensor" shall mean the copyright owner or entity authorized by
      the copyright owner that is granting the License.

      "Legal Entity" shall mean the union of the acting entity and all
      other entities that control, are controlled by, or are under common
      control with that entity. For the purposes of this definition,
      "control" means (i) the power, direct or indirect, to cause the
      direction or management of such entity, whether by contract or
      otherwise, or (ii) ownership of fifty percent (50%) or more of the
      outstanding shares, or (iii) beneficial ownership of such entity.

      "You" (or "Your") shall mean an individual or Legal Entity
      exercising permissions granted by this License.

      "Source" form shall mean the preferred form for making modifications,
      including but not limited to software source code, documentation
      source, and configuration files.

      "Object" form shall mean any form resulting from mechanical
      transformation or translation of a Source form, including but
      not limited to compiled object code, generated documentation,
      and conversions to other media types.

      "Work" shall mean the work of authorship, whether in Source or
      Object form, made available under the License, as indicated by a
      copyright notice that is included in or attached to the work
      (an example is provided in the Appendix below).

      "Derivative Works" shall mean any work, whether in Source or Object
      form, that is based on (or derived from) the Work and for which the
      editorial revisions, annotations, elaborations, or other modifications
      represent, as a whole, an original work of authorship. For the purposes
      of this License, Derivative Works shall not include works that remain
      separable from, or merely link (or bind by name) to the interfaces of,
      the Work and Derivative Works thereof.

      "Contribution" shall mean any work of authorship, including
      the original version of the Work and any modifications or additions
      to that Work or Derivative Works thereof, that is intentionally
      submitted to Licensor for inclusion in the Work by the copyright owner
      or by an individual or Legal Entity authorized to submit on behalf of
      the copyright owner. For the purposes of this definition, "submitted"
      means any form of electronic, verbal, or written communication sent
      to the Licensor or its representatives, including but not limited to
      communication on electronic mailing lists, source code control systems,
      and issue tracking systems that are managed by, or on behalf of, the
      Licensor for the purpose of discussing and improving the Work, but
      excluding communication that is conspicuously marked or otherwise
      designated in writing by the copyright owner as "Not a Contribution."

      "Contributor" shall mean Licensor and any individual or Legal Entity
      on behalf of whom a Contribution has been received by Licensor and
      subsequently incorporated within the Work.

   2. Grant of Copyright License. Subject to the terms and conditions of
      this License, each Contributor hereby grants to You a perpetual,
      worldwide, non-exclusive, no-charge, royalty-free, irrevocable
      copyright license to reproduce, prepare Derivative Works of,
      publicly display, publicly perform, sublicense, and distribute the
      Work and such Derivative Works in Source or Object form.

   3. Grant of Patent License. Subject to the terms and conditions of
      this License, each Contributor hereby grants to You a perpetual,
      worldwide, non-exclusive, no-charge, royalty-free, irrevocable
      (except as stated in this section) patent license to make, have made,
      use, offer to sell, sell, import, and otherwise transfer the Work,
      where such license applies only to those patent claims licensable
      by such Contributor that are necessarily infringed by their
      Contribution(s) alone or by combination of their Contribution(s)
      with the Work to which such Contribution(s) was submitted. If You
      institute patent litigation against any entity (including a
      cross-claim or counterclaim in a lawsuit) alleging that the Work
      or a Contribution incorporated within the Work constitutes direct
      or contributory patent infringement, then any patent licenses
      granted to You under this License for that Work shall terminate
      as of the date such litigation is filed.

   4. Redistribution. You may reproduce and distribute copies of the
      Work or Derivative Works thereof in any medium, with or without
      modifications, and in Source or Object form, provided that You
      meet the following conditions:

      (a) You must give any other recipients of the Work or
          Derivative Works a copy of this License; and

      (b) You must cause any modified files to carry prominent notices
          stating that You changed the files; and

      (c) You must retain, in the Source form of any Derivative Works
          that You distribute, all copyright, patent, trademark, and
          attribution notices from the Source form of the Work,
          excluding those notices that do not pertain to any part of
          the Derivative Works; and

      (d) If the Work includes a "NOTICE" text file as part of its
          distribution, then any Derivative Works that You distribute must
          include a readable copy of the attribution notices contained
          within such NOTICE file, excluding those notices that do not
          pertain to any part of the Derivative Works, in at least one
          of the following places: within a NOTICE text file distributed
          as part of the Derivative Works; within the Source form or
          documentation, if provided along with the Derivative Works; or,
          within a display generated by the Derivative Works, if and
          wherever such third-party notices normally appear. The contents
          of the NOTICE file are for informational purposes only and
          do not modify the License. You may add Your own attribution
          notices within Derivative Works that You distribute, alongside
          or as an addendum to the NOTICE text from the Work, provided
          that such additional attribution notices cannot be construed
          as modifying the License.

      You may add Your own copyright statement to Your modifications and
      may provide additional or different license terms and conditions
      for use, reproduction, or distribution of Your modifications, or
      for any such Derivative Works as a whole, provided Your use,
      reproduction, and distribution of the Work otherwise complies with
      the conditions stated in this License.

   5. Submission of Contributions. Unless You explicitly state otherwise,
      any Contribution intentionally submitted for inclusion in the Work
      by You to the Licensor shall be under the terms and conditions of
      this License, without any additional terms or conditions.
      Notwithstanding the above, nothing herein shall supersede or modify
      the terms of any separate license agreement you may have executed
      with Licensor regarding such Contributions.

   6. Trademarks. This License does not grant permission to use the trade
      names, trademarks, service marks, or product names of the Licensor,
      except as required for reasonable and customary use in describing the
      origin of the Work and reproducing the content of the NOTICE file.

   7. Disclaimer of Warranty. Unless required by applicable law or
      agreed to in writing, Licensor provides the Work (and each
      Contributor provides its Contributions) on an "AS IS" BASIS,
      WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or
      implied, including, without limitation, any warranties or conditions
      of TITLE, NON-INFRINGEMENT, MERCHANTABILITY, or FITNESS FOR A
      PARTICULAR PURPOSE. You are solely responsible for determining the
      appropriateness of using or redistributing the Work and assume any
      risks associated with Your exercise of permissions under this License.

   8. Limitation of Liability. In no event and under no legal theory,
      whether in tort (including negligence), contract, or otherwise,
      unless required by applicable law (such as deliberate and grossly
      negligent acts) or agreed to in writing, shall any Contributor be
      liable to You for damages, including any direct, indirect, special,
      incidental, or consequential damages of any character arising as a
      result of this License or out of the use or inability to use the
      Work (including but not limited to damages for loss of goodwill,
      work stoppage, computer failure or malfunction, or any and all
      other commercial damages or losses), even if such Contributor
      has been advised of the possibility of such damages.

   9. Accepting Warranty or Additional Liability. While redistributing
      the Work or Derivative Works thereof, You may choose to offer,
      and charge a fee for, acceptance of support, warranty, indemnity,
      or other liability obligations and/or rights consistent with this
      License. However, in accepting such obligations, You may act only
      on Your own behalf and on Your sole responsibility, not on behalf
      of any other Contributor, and only if You agree to indemnify,
      defend, and hold each Contributor harmless for any liability
      incurred by, or claims asserted against, such Contributor by reason
      of your accepting any such warranty or additional liability.

   END OF TERMS AND CONDITIONS

   APPENDIX: How to apply the Apache License to your work.

      To apply the Apache License to your work, attach the following
      boilerplate notice, with the fields enclosed by brackets "[]"
      replaced with your own identifying information. (Don't include
      the brackets!)  The text should be enclosed in the appropriate
      comment syntax for the file format. We also recommend that a
      file or class name and description of purpose be included on the
      same "printed page" as the copyright notice for easier
      identification within third-party archives.

   Copyright [yyyy] [name of copyright owner]

   Licensed under the Apache License, Version 2.0 (the "License");
   you may not use this file except in compliance with the License.
   You may obtain a copy of the License at

       http://www.apache.org/licenses/LICENSE-2.0

   Unless required by applicable law or agreed to in writing, software
   distributed under the License is distributed on an "AS IS" BASIS,
   WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied.
   See the License for the specific language governing permissions and
   limitations under the License.
```


---

## MIT License — Moonshine

Reproduced from the `LICENSE` file of
`https://huggingface.co/csukuangfj/sherpa-onnx-moonshine-tiny-en-int8` at the
pinned commit.

```text
MIT License

Copyright (c) 2024 Useful Sensors

Permission is hereby granted, free of charge, to any person obtaining a copy
of this software and associated documentation files (the "Software"), to deal
in the Software without restriction, including without limitation the rights
to use, copy, modify, merge, publish, distribute, sublicense, and/or sell
copies of the Software, and to permit persons to whom the Software is
furnished to do so, subject to the following conditions:

The above copyright notice and this permission notice shall be included in all
copies or substantial portions of the Software.

THE SOFTWARE IS PROVIDED "AS IS", WITHOUT WARRANTY OF ANY KIND, EXPRESS OR
IMPLIED, INCLUDING BUT NOT LIMITED TO THE WARRANTIES OF MERCHANTABILITY,
FITNESS FOR A PARTICULAR PURPOSE AND NONINFRINGEMENT. IN NO EVENT SHALL THE
AUTHORS OR COPYRIGHT HOLDERS BE LIABLE FOR ANY CLAIM, DAMAGES OR OTHER
LIABILITY, WHETHER IN AN ACTION OF CONTRACT, TORT OR OTHERWISE, ARISING FROM,
OUT OF OR IN CONNECTION WITH THE SOFTWARE OR THE USE OR OTHER DEALINGS IN THE
SOFTWARE.
```

---

## MIT License — Supertonic

Reproduced from the `LICENSE` file of
`https://huggingface.co/csukuangfj2/sherpa-onnx-supertonic-3-tts-int8-2026-05-11`
at the pinned commit — the same file this distribution packages beside the
weights.

```text
MIT License

Copyright (c) 2025 Supertone Inc.

Permission is hereby granted, free of charge, to any person obtaining a copy
of this software and associated documentation files (the "Software"), to deal
in the Software without restriction, including without limitation the rights
to use, copy, modify, merge, publish, distribute, sublicense, and/or sell
copies of the Software, and to permit persons to whom the Software is
furnished to do so, subject to the following conditions:

The above copyright notice and this permission notice shall be included in all
copies or substantial portions of the Software.

THE SOFTWARE IS PROVIDED "AS IS", WITHOUT WARRANTY OF ANY KIND, EXPRESS OR
IMPLIED, INCLUDING BUT NOT LIMITED TO THE WARRANTIES OF MERCHANTABILITY,
FITNESS FOR A PARTICULAR PURPOSE AND NONINFRINGEMENT. IN NO EVENT SHALL THE
AUTHORS OR COPYRIGHT HOLDERS BE LIABLE FOR ANY CLAIM, DAMAGES OR OTHER
LIABILITY, WHETHER IN AN ACTION OF CONTRACT, TORT OR OTHERWISE, ARISING FROM,
OUT OF OR IN CONNECTION WITH THE SOFTWARE OR THE USE OR OTHER DEALINGS IN THE
SOFTWARE.
```
