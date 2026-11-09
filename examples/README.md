# Open 10 real episodes from v1.1.0

From the repository root, with Python 3.10+:

```sh
gh release download v1.1.0 -R www080327-glitch/mimo-distillation-dataset \
  -p MANIFEST.json -p mimo-episodes-v1.jsonl.gz -p mimo-episode-media-v1-004.tar -D sample-release
python3 replay_episode.py sample-release/MANIFEST.json --port 11840
```

Open <http://127.0.0.1:11840/>. The three files (about 65 MiB total) are also available in the [v1.1.0 Release](https://github.com/www080327-glitch/mimo-distillation-dataset/releases/tag/v1.1.0). Stop the local viewer with Ctrl+C. No login, SQLite, model, extra Python packages, or project renderer is needed. The viewer reads PNG members in place; it does not unpack the tar or serve the download directory.

Open the first **agent · completed** example to see the recorded tool returns, five index revisions, and the initial and last retained project ZIPs. At the step where the teacher actually read the released requirement, the complete tool return provides the missing Markdown file. In **agent · failed** `e64c00573475…`, the tool announced a runtime file and no full read was recorded; the page names the missing file. The **files · incomplete** example has source files and a tool return but no images.

- **Historical replay** displays archived turns and observations in step order. An initial tool preview precedes step 1; unpaired events stay unpaired. A failed or incomplete episode retains its recorded status and last available files.
- **Recorded teacher input** means an image reference attached to a saved request. **Archived tool preview** means a separate tool output. Public PNGs have been normalized and container metadata removed; PNG file hashes refer to the public copies. Neither an archived preview nor a new render should be substituted for a missing teacher input.
- **Project recovery** overlays the archived HTML revisions on the initial project files and includes announced runtime files from their first complete recorded tool read onward. The ZIPs hold source files. No dependency or other unrecorded file is reconstructed, and the last retained snapshot does not certify a complete final workspace.
- **Re-execution** is `NOT_RUN`. Source is displayed as text, with no generated JavaScript, iframe, or automatic external request. Episode records identify the teacher per request; v1.1.0 episodes do not carry an episode-specific source license. See [NOTICE](../NOTICE) for what the release license covers.

The [recovery receipts](v1.1.0-recovery.json) record all 10 distinct IDs, state, tool return counts, file fingerprints for each available snapshot, and all 60 ordered image references (32 distinct PNGs). The sample covers 4 completed, 2 failed and 4 incomplete episodes; it was chosen for coverage. Generate it again:

```sh
python3 replay_episode.py sample-release/MANIFEST.json --receipt recovery.json
cmp recovery.json examples/v1.1.0-recovery.json
```

For different v1.1.0 episodes, pass `--ids` with one full public ID per line. Missing references name the shard; for split tar files, list and download the required pieces, then point the reader to the rebuilt directory:

```sh
python3 reassemble_media.py sample-release/MANIFEST.json \
  --asset mimo-episode-media-v1-001.tar --list-parts
python3 reassemble_media.py sample-release/MANIFEST.json \
  --asset mimo-episode-media-v1-001.tar --out restored
python3 replay_episode.py sample-release/MANIFEST.json --ids my-ids.txt \
  --media-dir restored --port 11840
```

## Open A/B/C releases (v1.2.0 and later)

Download the tar and checksum from the [Releases page](https://github.com/www080327-glitch/mimo-distillation-dataset/releases). For an increment, download any base tars named by its manifest. Pass each one as a separate `--base-tar` argument.

```sh
python3 replay_episode.py mimo-nextgen-abc-v1.3.0.tar.gz --abc-tar \
  --base-tar mimo-nextgen-abc-v1.tar.gz --port 11840
```

The viewer labels teacher input images separately from tool previews. It shows recorded edits and offers separate initial and retained project ZIPs when all their files are available. It doesn't execute the episode code. A missing base shows actionable errors; other recorded content remains readable.

For release checks, use `--receipt recovery.json --strict` in place of `--port 11840`. A missing or invalid asset in a selected episode exits 1 after writing the receipt. Use `--ids` to select specific full episode IDs; omit it to inspect all episodes in the tar.

If a large download was interrupted, save its release checksum file and use the
resumable downloader. Re-run the same command to continue the `.part` file;
the final filename appears only after SHA-256 verification.

```sh
python3 download_release.py v1.3.0 mimo-nextgen-abc-v1.3.0.tar.gz SHA256SUMS downloads
```

### Check bases and share a smaller replay

Save the release's standalone `MANIFEST.json` next to your local files. The
first command checks local hashes without making network requests. Add
`--fetch` only when you want to download the missing declared bases.
Transient gateway errors are retried once; interrupted downloads keep their
partial files. The JSON report lists each pinned SHA-256 and includes
`replay_args` only when every base verifies. Pass that array as individual
arguments to the replay command (paths with spaces remain single arguments).

```sh
python3 download_abc_bases.py MANIFEST.json releases
```

Put one episode ID per line in `ids.txt`. Pass the release tar and any needed
bases to the exporter. It checks the selected evidence and copies only those
episodes and their verified assets. The output is a sample, not a release
increment. It can be reopened without any bases.

```sh
python3 export_replay.py RELEASE.tar.gz --ids ids.txt --base-tar BASE.tar.gz --output portable.tar.gz
python3 replay_episode.py portable.tar.gz --abc-tar --strict --receipt portable.json
```

For offline release counts, pass one manifest per version. Include the
original v1.2.0 archive to verify its ten IDs; its manifest does not list them.

```sh
python3 audit_abc_releases.py manifests/*.json --legacy-archive mimo-nextgen-abc-v1.tar.gz
```

The base planner also accepts an archive in place of `MANIFEST.json`; that
reads only the embedded metadata and does not certify the archive contents.
To see which local archives actually provide the assets for a selection, use
`export_replay.py --plan` instead of `--output`, with the same archive,
`--ids` and repeated `--base-tar` options.

To verify that a sample preserves its parent release's recorded rows and
referenced assets, provide both archives. Older samples may also need their
declared bases; self-contained exports do not.

```sh
python3 verify_replay_sample.py RELEASE.tar.gz portable.tar.gz
```

### Inspect a recorded step or check a release before sharing it

These commands use already-downloaded archives. Pass the same needed
`--base-tar` options for the selected episode. A step ZIP contains only
recorded files; the tool never re-executes the project.

```sh
python3 restore_replay_step.py RELEASE.tar.gz --episode EPISODE_ID --step 8 --base-tar BASE.tar.gz --output step-8.zip
python3 verify_abc_tallies.py RELEASE.tar.gz
python3 smoke_replay_http.py portable.tar.gz --episode EPISODE_ID
```

When you have the release's official checksum file, check the locally
downloaded archive and its standalone manifest before using either:

```sh
python3 check_abc_release.py RELEASE.tar.gz MANIFEST.json SHA256SUMS
```

This verifies both pinned files and checks that the archive contains the
same manifest. It does not download or run the archived projects.

For a release-wide version-chain check, run `audit_replay_history.py`
on the local archive. This compares recorded references to the retained
workspace hashes, and does not imply that file bytes were read. Add
`--verify-files` and any required `--base-tar` arguments to verify
workspace file bytes as well. Missing historical versions are reported as
gaps rather than reconstructed by guesswork.

`restore_replay_step.py --receipt step.json` writes the episode ID, step,
verified file hashes and deterministic ZIP hash in a separate JSON file.

To check a received step ZIP against its receipt without extracting it:

```sh
python3 verify_step_receipt.py step-8.zip step-8.json
```

This checks the ZIP and its members against the supplied receipt. It does
not authenticate the original release; use the pinned release check for that.

If you have a trusted list of expected screenshot SHA-256 values, add
`--expected-pngs screenshots.txt` to the smoke command. It checks the
exact distinct rendered set as well as each file's bytes; an empty list
explicitly expects no screenshots.

To also check that a receipt matches the archived workspace at its stated
step, add `--source-archive RELEASE.tar.gz` and any needed base archives.
Add `--source-sha256 HASH` to check the archive against a SHA-256 value
from trusted release checksums.
