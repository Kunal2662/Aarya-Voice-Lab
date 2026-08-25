# Public Dataset Acquisition Readiness

Task 2 of the current autonomous execution plan (Public Dataset
Authorization + Real Intake). **No dataset has been downloaded.**
Explicit authorization to download and use a specific dataset was not
given this session, and per this project's own operating rule,
downloading any file — regardless of size or license — requires the
user's explicit permission granted in chat, not inferred from a
dataset's license being permissive. This document is the "exact
acquisition instructions" the task asks for in that situation: real,
independently verified candidate research, so a future authorized
session can register and use one quickly and correctly.

## Candidates evaluated

Both entries below were checked directly against their live, official
source pages during this session (not recalled from training data
alone) — see each entry's "Verified" line.

### 1. CSTR VCTK Corpus (recommended primary candidate)

| Field | Value |
|---|---|
| Source | University of Edinburgh, Centre for Speech Technology Research (CSTR) — Edinburgh DataShare |
| URL | https://datashare.ed.ac.uk/handle/10283/3443 |
| Persistent identifier | https://doi.org/10.7488/ds/2645 |
| Version | 0.92 |
| License | **CC BY 4.0** (Creative Commons Attribution 4.0 International) |
| Size | `VCTK-Corpus-0.92.zip`, 10.94 GB |
| Content | 110 English speakers, ~400 sentences each, ~44 hours, 48 kHz/16-bit, single-channel |
| Speaker metadata | Per-speaker: age, gender, accent, region (volunteer research-corpus participants — not the AARYA project's target speaker, no Class C overlap) |
| Citation required | Yes — see the DataShare page for the exact citation string |
| Verified | Checked live via `datashare.ed.ac.uk` (dataset page) and independently corroborated via `huggingface.co/datasets/CSTR-Edinburgh/vctk`'s dataset card (`License: cc-by-4.0`), this session |

**Why recommended:** CC BY 4.0 is permissive (commercial and
non-commercial use, attribution only), the corpus is purpose-built for
multi-speaker TTS/voice-cloning research (explicitly stated on its own
page: "suitable for DNN-based multi-speaker text-to-speech synthesis
systems"), and per-utterance speaker metadata is already present and
consented — directly matching this project's Track A (public licensed
data) use cases: training-pipeline development, model experimentation,
benchmarking.

### 2. LibriSpeech ASR corpus

| Field | Value |
|---|---|
| Source | OpenSLR (SLR12) |
| URL | https://www.openslr.org/12/ |
| License | **CC BY 4.0** |
| Size | Multiple subsets from 337 MB (`dev-clean`) to 30 GB (`train-other-500`); full corpus ~1000 hours |
| Content | Read English speech derived from LibriVox public-domain audiobooks, aligned to Project Gutenberg texts |
| Speaker metadata | Not documented on the resource page itself — would need verification against `raw-metadata.tar.gz` before relying on any per-speaker field |
| Checksum | `md5sum.txt` provided for every archive — usable for the registry's `checksum_sha256` field once actually downloaded and re-hashed (the published sums are MD5, not SHA-256; this project's registry schema requires SHA-256, so the archive would need to be hashed after download, not merely have the published MD5 copied in) |
| Verified | Checked live via `openslr.org/12`, this session |

**Why secondary:** Built for ASR, not TTS; much larger; speaker
metadata richness is unconfirmed without further verification. A
smaller subset (`dev-clean`, 337 MB) would be the right starting point
if this candidate is chosen, per this project's own "smallest
meaningful experiment first" discipline.

### 3. Common Voice (Mozilla) — not evaluated to the same depth

Not independently re-verified this session. Common Voice's license and
access terms have changed across releases (some releases require
agreeing to Mozilla's terms via a web form rather than a direct
archive link) — do not rely on prior general knowledge of this dataset
without checking `commonvoice.mozilla.org`'s current terms directly at
acquisition time.

## What "explicit authorization" means for this project

Per `docs/DATA_POLICY.md`, two separate gates apply before any of the
above may be used, and neither has been cleared:

1. **Licensing review** — reading and recording the license, permitted
   uses, and any restrictions in the `PublicDatasetRegistry` (this
   document is the first half of that review for VCTK/LibriSpeech; a
   human should still confirm before registering).
2. **Download authorization** — the user's explicit, in-chat "yes,
   download X" for the specific archive and its real size. A
   permissive license does not substitute for this.

## Exact next steps once authorization is given

```bash
# Example for VCTK — adjust for whichever candidate is actually approved.
curl -LO https://datashare.ed.ac.uk/bitstream/handle/10283/3443/VCTK-Corpus-0.92.zip
sha256sum VCTK-Corpus-0.92.zip   # record this in the registry entry below
```

```python
from aarya_voice_lab.registry.dataset_registry import PublicDatasetRegistry
from aarya_voice_lab.schemas.records import build_public_dataset_entry

registry = PublicDatasetRegistry()
registry.add(build_public_dataset_entry(
    dataset_id="vctk-corpus-0.92",
    dataset_name="CSTR VCTK Corpus",
    version="0.92",
    source="https://doi.org/10.7488/ds/2645",
    license="CC BY 4.0",
    permitted_uses=["training-pipeline-development", "model-experimentation", "benchmark-development"],
    status="approved",  # only after a human has actually reviewed the above
    language=["en"],
    speaker_metadata_restrictions=None,  # volunteer research-corpus consent; not personal data
    provenance="downloaded from University of Edinburgh DataShare, <acquisition date>",
    checksum_sha256="<real sha256 of the downloaded archive, computed after download>",
    citation="Yamagishi, Junichi; Veaux, Christophe; MacDonald, Kirsten. (2019). "
             "CSTR VCTK Corpus (version 0.92). University of Edinburgh CSTR. "
             "https://doi.org/10.7488/ds/2645",
))
```

Then run `pipeline.public_dataset_gate.evaluate_public_dataset_use()`
to confirm the gate clears before any adapter/preprocessing work
touches the downloaded content — never assumed, always checked.

## What this document does not do

Does not download anything. Does not register anything (the code
snippet above is illustrative, not executed). Does not decide which
candidate to use — that remains the user's call. `PublicDatasetRegistry`
and `public_dataset_gate` are unchanged.
