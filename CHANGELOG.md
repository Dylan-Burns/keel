# Changelog

All notable changes to this project are documented in this file. The format
follows [Keep a Changelog](https://keepachangelog.com/en/1.1.0/), and
release-please maintains the released sections from Conventional Commits.

## [0.6.1](https://github.com/Dylan-Burns/keel/compare/v0.6.0...v0.6.1) (2026-10-23)


### Bug fixes

* **citations:** link a table citation to the cited row, not the title ([ad984e6](https://github.com/Dylan-Burns/keel/commit/ad984e64f21c11234741e07fdb6ad0b5e9f29c77))
* **retriever:** log the missing cgroup quota instead of a bare pass ([c242de5](https://github.com/Dylan-Burns/keel/commit/c242de586116404583c86d051969ee685db224c1))

## [0.6.0](https://github.com/Dylan-Burns/keel/compare/v0.5.0...v0.6.0) (2026-10-23)


### Features

* **eval:** report the rerank time of each question ([582cb82](https://github.com/Dylan-Burns/keel/commit/582cb824a82fb374713d8e909c5af20e23c96c89))


### Performance

* **retriever:** tune the cross-encoder length, threads, and batch size ([baef6ff](https://github.com/Dylan-Burns/keel/commit/baef6ffb900c43339130ac7a93c00bea71c6edc2))


### Documentation

* **docs:** record the latency experiments and the reranker tuning ([6234dc7](https://github.com/Dylan-Burns/keel/commit/6234dc7ba7153c0e1ac7d776eb6069d2135d4fd6))

## [0.5.0](https://github.com/Dylan-Burns/keel/compare/v0.4.3...v0.5.0) (2026-10-23)


### Features

* **api:** locate cited chunks and add the filing reader route ([07da566](https://github.com/Dylan-Burns/keel/commit/07da566750608402a2f48796293f2b46a9a5e46e))
* **web:** show the citation location and open the filing reader ([4886cbf](https://github.com/Dylan-Burns/keel/commit/4886cbf37f7533045f49a049ea622de485a8c28f))


### Bug fixes

* **web:** render admin jobs that have no progress yet ([1c846ff](https://github.com/Dylan-Burns/keel/commit/1c846ffb84768fe3d41324516160e154b3b04b65))


### Documentation

* **docs:** record the citation location and the filing reader ([71ab577](https://github.com/Dylan-Burns/keel/commit/71ab5776a9ec07db5b36ec2c83b780730b8940cc))

## [0.4.3](https://github.com/Dylan-Burns/keel/compare/v0.4.2...v0.4.3) (2026-10-23)


### Bug fixes

* **eval:** write the eval job report to a writable folder ([780a8ba](https://github.com/Dylan-Burns/keel/commit/780a8baee9c56c8b5726878e919c6004df817bdc))
* **infra:** keep backups and eval reports on the host volumes ([fb03ada](https://github.com/Dylan-Burns/keel/commit/fb03adaa3009bae59a2e671b3f232e63eb7c1bb6))


### Documentation

* **docs:** record the eval job fix for a read-only host ([653e062](https://github.com/Dylan-Burns/keel/commit/653e06277d4fa36b4520063a78bfb41969c08485))

## [0.4.2](https://github.com/Dylan-Burns/keel/compare/v0.4.1...v0.4.2) (2026-10-23)


### Bug fixes

* **infra:** drop pip from the runtime image ([db60477](https://github.com/Dylan-Burns/keel/commit/db604774c449686d9759f8231efa275c42967ab3))
* **infra:** users file on the state volume, corpus extracted as the app ([0163790](https://github.com/Dylan-Burns/keel/commit/0163790f3203827bb82959a36b036b2a4e8b6a61))

## [0.4.1](https://github.com/Dylan-Burns/keel/compare/v0.4.0...v0.4.1) (2026-10-23)


### Bug fixes

* **infra:** keep root deploy steps from following app-made symlinks ([ca2ff3e](https://github.com/Dylan-Burns/keel/commit/ca2ff3ef51f3b34723f8c6f53238d0030aee4176))
* **infra:** writable corpus and company dictionary on the host ([60c2fc3](https://github.com/Dylan-Burns/keel/commit/60c2fc355fca83860e4d92cff3fff1ef5e01f032))
* **release:** scan the image for package vulnerabilities only ([1c145a9](https://github.com/Dylan-Burns/keel/commit/1c145a967ab3ac9ab02f0de827e6b9c0bf255559))

## [0.4.0](https://github.com/Dylan-Burns/keel/compare/v0.3.0...v0.4.0) (2026-10-22)


### Features

* **infra:** cloudfront address in front of the aws host ([2abb946](https://github.com/Dylan-Burns/keel/commit/2abb946d3eafc021d3640958623832356360adf9))
* **infra:** deploy from an s3 bundle without github downloads ([5ca3acf](https://github.com/Dylan-Burns/keel/commit/5ca3acfb291aa8983fcaaabd3362ecc99f27351c))
* **web:** add the admin pages behind a role-gated shell ([1ce257e](https://github.com/Dylan-Burns/keel/commit/1ce257ee97ec6fb92b02239e5dd07b6a50dba213))
* **web:** add the debug page for understand and retrieve ([2e1b9e8](https://github.com/Dylan-Burns/keel/commit/2e1b9e86f3224b2e6f6f586817712fa5a698f782))
* **web:** download the answer memo as markdown or docx ([687f416](https://github.com/Dylan-Burns/keel/commit/687f4169bace95ac1fa133f80150a8491e02b0bb))


### Bug fixes

* **infra:** run the bundle from a private temp dir, check the tag commit ([0c21bd4](https://github.com/Dylan-Burns/keel/commit/0c21bd41840aad2aaa66d136d428b344375d266b))
* **infra:** run the ssm deploy command without bash-only options ([a21f987](https://github.com/Dylan-Burns/keel/commit/a21f987315e057e5834c2d40baa478fde51e8190))
* **release:** lowercase the image name for the sbom, scan, and attest ([ea05642](https://github.com/Dylan-Burns/keel/commit/ea05642e190bb0a4a7a036d86785bc77d81637b9))
* **web:** address the review and map the cli to the web ui ([ad88e81](https://github.com/Dylan-Burns/keel/commit/ad88e81e290ea05c9c693d9a294585d739d766f7))


### Documentation

* **docs:** remove the demo preparation files from the public repo ([8555cd5](https://github.com/Dylan-Burns/keel/commit/8555cd5033d8489cc17f270750f3d04fe984d0d4))

## [0.3.0](https://github.com/Dylan-Burns/keel/compare/v0.2.0...v0.3.0) (2026-10-22)


### Features

* **api:** add the admin job runner and the admin routes ([223daed](https://github.com/Dylan-Burns/keel/commit/223daed9779ac58b328a158ed6b7748c23cf3fe7))
* **api:** add the watch list and the debug routes ([ed0c4f2](https://github.com/Dylan-Burns/keel/commit/ed0c4f2fea123ed12a05c1eba187b474d956712e))
* **cli:** add the history, share, coverage, and jobs commands ([1466a51](https://github.com/Dylan-Burns/keel/commit/1466a51e266e808d792d717c5d093c934aeee140))
* **infra:** deploy the aws host through ssm and github oidc ([7705665](https://github.com/Dylan-Burns/keel/commit/770566533f7f77f657e3bd6fae90461d2ff14cfd))
* **infra:** terraform plan and drift check in ci, release starts deploy ([3721bdf](https://github.com/Dylan-Burns/keel/commit/3721bdfd5a67f1bb64a583234e3209850b741ad1))
* **web:** show cited IDs in the answer text as citation chips ([d98de49](https://github.com/Dylan-Burns/keel/commit/d98de494f9b97ccc5fccdf3b67b02ac679c18a01))


### Bug fixes

* **api:** break the state and jobs import cycle ([1e9e162](https://github.com/Dylan-Burns/keel/commit/1e9e162c1d75a07921ef55d6684e9b05724481e5))
* **eval:** hold the judge gates pending below 5 judged answers ([23cb439](https://github.com/Dylan-Burns/keel/commit/23cb43949f40cd7c6da7dbfd4a30eb3f9481e1e2))
* **infra:** install the aws cli by snap and pin an existing trivy tag ([5f5c8e4](https://github.com/Dylan-Burns/keel/commit/5f5c8e48222f6067147d26c3f24cbf8c86a5492f))
* **infra:** match the release tag exactly when resolving its commit ([97d153f](https://github.com/Dylan-Burns/keel/commit/97d153f7c45aec7844b3963d0805e543f8d18117))
* **infra:** plan with aws credentials on main only, narrower reads ([34446fb](https://github.com/Dylan-Burns/keel/commit/34446fb36ffb48e852c94ee374884af7f23dc3fe))
* **infra:** prefer the peeled commit of an annotated release tag ([f567461](https://github.com/Dylan-Burns/keel/commit/f567461039fb0c1854a4c27a5ff209e26f2859e0))
* **infra:** run the deploy script by commit and pin trivy by sha ([ab1aecb](https://github.com/Dylan-Burns/keel/commit/ab1aecb2a45659fb01c3a432663aa317aaa0c2d8))
* **release:** bump the keel version in uv.lock with each release ([8a65375](https://github.com/Dylan-Burns/keel/commit/8a653751b49dce28cb8c4a156468ec91bfb0fd0a))
* **web:** name unverified inline chips and keep link brackets ([56e2e5f](https://github.com/Dylan-Burns/keel/commit/56e2e5ff15eb83f9fbd9ad6a2af9eda693ed3945))


### Documentation

* **docs:** count the tests after the rebase on main ([b0c9a49](https://github.com/Dylan-Burns/keel/commit/b0c9a49241c91dd85c09318098004c0b34c7c4a9))
* **docs:** document the admin API and the CLI parity commands ([3dcc229](https://github.com/Dylan-Burns/keel/commit/3dcc22990a542bf5b9d6f584aebc67030fe58079))
* **docs:** record the inline citation chips follow-up ([be53d76](https://github.com/Dylan-Burns/keel/commit/be53d76ea6cca970a46e7e52585d87cca50278de))
* **eval:** document the minimum sample rule of the judge gates ([b169cd1](https://github.com/Dylan-Burns/keel/commit/b169cd1ffe65311f2fae3b28743e2e504748f1a1))
* **infra:** the aws ci and cd pipeline in the infra readme ([c13636c](https://github.com/Dylan-Burns/keel/commit/c13636c5605f2b33a1df403e2e1ae8447ea354c7))

## [0.2.0](https://github.com/Dylan-Burns/keel/compare/v0.1.0...v0.2.0) (2026-10-22)


### Features

* **api:** breaker, fallback, budget stop, degraded mode ([54d7c3b](https://github.com/Dylan-Burns/keel/commit/54d7c3ba431e4304d58a606948221b9c1e612ad6))
* **api:** eval page and adversarial preset ([9464c99](https://github.com/Dylan-Burns/keel/commit/9464c9911fa3d981a5e16499f0d2212dc975da59))
* **api:** feedback ([13cfe30](https://github.com/Dylan-Burns/keel/commit/13cfe3077546623accd20c6512e8d5d77a7d3edf))
* **api:** history and shareable links ([ac90e7c](https://github.com/Dylan-Burns/keel/commit/ac90e7c96ba50f1f2b5e8f793326c8ee6c4dfe2c))
* **api:** routes, SSE stream, auth, rate limit, static front-end ([86b3eaa](https://github.com/Dylan-Burns/keel/commit/86b3eaa5c67ff1c564f28846fe78fd786fdb755a))
* **api:** security controls S-01 to S-11 ([c3c6ca6](https://github.com/Dylan-Burns/keel/commit/c3c6ca6d5a8438dcb05a5a1ee4eb55d95ea14855))
* **api:** users and tokens ([c6021b5](https://github.com/Dylan-Burns/keel/commit/c6021b5b4e05d372926c0df56e704e0ed75eb9ec))
* **cache:** warm-cache command and facts pre-fetch ([64b1efd](https://github.com/Dylan-Burns/keel/commit/64b1efd29095a160f0a420168a502592a125c7fb))
* **chunker:** token chunks with overlap and simhash ([7448f64](https://github.com/Dylan-Burns/keel/commit/7448f6416309ddfcb55db08683e940f615af31b8))
* **citations:** validator, answer cache, audit log ([33bf11e](https://github.com/Dylan-Burns/keel/commit/33bf11eab3d63ad881666267628441dde4b89960))
* **cli:** bootstrap ([1169a98](https://github.com/Dylan-Burns/keel/commit/1169a98f8561e5f3c7b8837882488df122fed83a))
* **cli:** keel calibrate measures the token calibration factor ([742d818](https://github.com/Dylan-Burns/keel/commit/742d81867752497fb83784496e2e33b338425de2))
* **cli:** keel parse with --all and --summary ([1766a5c](https://github.com/Dylan-Burns/keel/commit/1766a5c86e67cd982e041490d3879959c69adbbd))
* **cli:** keel retrieve prints the planned context ([31e5053](https://github.com/Dylan-Burns/keel/commit/31e5053deaa3fc46da57ad12d822e081aa01822a))
* **cli:** keel understand prints the question analysis ([a58b936](https://github.com/Dylan-Burns/keel/commit/a58b936670cbcb8527f4d19afa493702e737d5fe))
* **cli:** pilot metrics script ([5fbff9a](https://github.com/Dylan-Burns/keel/commit/5fbff9ae7d002b9d0ae41dee0cde69be4a838bc5))
* **edgar:** html to text and incremental add ([3ec1906](https://github.com/Dylan-Burns/keel/commit/3ec19068456edb417c58cb5c49570359cb13854e))
* **edgar:** submissions and filing download ([28fe392](https://github.com/Dylan-Burns/keel/commit/28fe3929fbe6cf068df6c054a1f5283107b13efd))
* **edgar:** ticker map and company facts with cache ([c5ff51b](https://github.com/Dylan-Burns/keel/commit/c5ff51ba050e0b9f89d1e3be99060b8c8e401200))
* **edgar:** watch list and refresh ([e66c80b](https://github.com/Dylan-Burns/keel/commit/e66c80bb8c1d7b25662de7981a2e70577564f909))
* **eval:** golden set and section-level labels ([d01b1e0](https://github.com/Dylan-Burns/keel/commit/d01b1e0084def3eace0c94ee4c4a6474a2787a1a))
* **eval:** judge and answer metrics ([d2fab6d](https://github.com/Dylan-Burns/keel/commit/d2fab6dd84f4bd391aa38796a196f38e54fa4d1f))
* **eval:** retrieval metrics, ablation, gates ([c16608f](https://github.com/Dylan-Burns/keel/commit/c16608f4119da60e21ba435fb47c57f2aa83dac7))
* **export:** docx memo ([c8cec87](https://github.com/Dylan-Burns/keel/commit/c8cec8792e7a799d8d7029147c0c486f4ec96100))
* **export:** log each memo export for the pilot metrics ([c501191](https://github.com/Dylan-Burns/keel/commit/c50119124e6809bf216d1058c3e6b09e43464667))
* **export:** markdown memo ([3b1f4b0](https://github.com/Dylan-Burns/keel/commit/3b1f4b041602c092178cdefbfbc1941f689b478b))
* **index:** chunk store and FTS5 lexical index ([10cd5fb](https://github.com/Dylan-Burns/keel/commit/10cd5fbb44fc4b63234b48b912c099cf654a8ebe))
* **index:** dense vectors with the pinned embedding model ([4a4f042](https://github.com/Dylan-Burns/keel/commit/4a4f042b814a025cfdd300ef79ac4c89e3cd98e9))
* **index:** manifest, current pointer, incremental build ([c77e125](https://github.com/Dylan-Burns/keel/commit/c77e12593fbd43323297ce38c81bc628ed8c93bb))
* **infra:** keep the memo export log in the backup ([af8bd03](https://github.com/Dylan-Burns/keel/commit/af8bd03f5937fd791131c1c000e68a61ce466e15))
* **infra:** restore the index archive from index.url over https ([cb91f37](https://github.com/Dylan-Burns/keel/commit/cb91f376e592913988274e81377d5abb5da618bf))
* **infra:** scheduler backup and restore test ([e422374](https://github.com/Dylan-Burns/keel/commit/e422374766aeac21d9a8e4d2da2d71672f2c3896))
* **infra:** serve with bootstrap and the refresh job ([582482b](https://github.com/Dylan-Burns/keel/commit/582482bddf63b5e56a4ab8646d8ce609f1dca859))
* **infra:** warn on a draft webm recording in the pre-flight ([3053869](https://github.com/Dylan-Burns/keel/commit/3053869e38f0a4ae916b17092762edca76e407bb))
* **parser:** header, XBRL cut, cover page, fiscal math, and checks ([a0d9a1b](https://github.com/Dylan-Burns/keel/commit/a0d9a1b11153731b5b10a8b2fde2a855c589beff))
* **parser:** table rebuild with units ([0fd5734](https://github.com/Dylan-Burns/keel/commit/0fd5734aa01ec9cab1aeb5dbef64d75176627ea9))
* **prompt:** claim support rules in prompt 1.5.0 ([b46ab68](https://github.com/Dylan-Burns/keel/commit/b46ab68e6317e58af2656893f1c931cacb4b5311))
* **prompt:** facts block and fact citations ([0e2223a](https://github.com/Dylan-Burns/keel/commit/0e2223a47f09f4d79e19811a15b0ab45940f822e))
* **prompt:** iterations from the 3 answers ([46e319a](https://github.com/Dylan-Burns/keel/commit/46e319a7662fc84dbf6b406f31a745e724361922))
* **prompt:** keep instruction chunks out of findings in prompt 1.5.1 ([3ddde2f](https://github.com/Dylan-Burns/keel/commit/3ddde2f491d4a9a0db04a4a9aad16916df074548))
* **prompt:** make prompt 1.5.1 the default ([26cd4bd](https://github.com/Dylan-Burns/keel/commit/26cd4bd59ed8ae5b54bfee202966ca2cb9676a3e))
* **provider:** adapter, mock with request counter, prompt 1.0.0 ([487d3e1](https://github.com/Dylan-Burns/keel/commit/487d3e18e61dba78a8ce8d73700c451caed02751))
* **retriever:** hybrid retrieval with RRF and the reranker ([c8c499b](https://github.com/Dylan-Burns/keel/commit/c8c499b14e5a775d7d8b0bf2fb6781a02741195b))
* **retriever:** reserve a response quota for risk questions ([f104079](https://github.com/Dylan-Burns/keel/commit/f104079c018671cb635ec3b5aa7b4d129fd3fc3a))
* **sections:** canonical section detector ([d072be9](https://github.com/Dylan-Burns/keel/commit/d072be9f9e26d013279751062c02a9546f939c41))
* **stage-01:** config loader and repo skeleton ([8f34792](https://github.com/Dylan-Burns/keel/commit/8f347921cde0aa7cd9e9af37080a0a385431a768))
* **stage-01:** zip extraction with safety checks and inventory ([1e66836](https://github.com/Dylan-Burns/keel/commit/1e66836d0940eb1d30fec1ccc5c1fa84a9009bbb))
* **understanding:** comp sets and templates ([fb920a2](https://github.com/Dylan-Burns/keel/commit/fb920a29df0f13e1b32de06f6224d018f56f14ef))
* **understanding:** entities, groups, time scope, types, and flags ([4765a3a](https://github.com/Dylan-Burns/keel/commit/4765a3a2549e99fe1410d162cfc33a2783d1cd1f))
* **web:** add theme tokens and a persisted dark mode toggle ([cbea8d3](https://github.com/Dylan-Burns/keel/commit/cbea8d393e77144090ce45c94c9a4fb34fda3b49))
* **web:** answer-trace drawer ([94d3d5d](https://github.com/Dylan-Burns/keel/commit/94d3d5dae2fdb38ca0c1f6fdcecb48a0297ec06e))
* **web:** comp sets page, templates, and thumbs votes ([8c8e848](https://github.com/Dylan-Burns/keel/commit/8c8e84827bc1d7a141c3a6a241406390bbd199cc))
* **web:** data use page ([e3462ce](https://github.com/Dylan-Burns/keel/commit/e3462cecaaac2b0da79d9d944ee92a4b70a01ec5))
* **web:** history page ([abbc63a](https://github.com/Dylan-Burns/keel/commit/abbc63a0bbe456a8fccf23806d3dc3debf0d5ee0))
* **web:** motion presets and the animations of 14.8 ([b608bac](https://github.com/Dylan-Burns/keel/commit/b608bace77af80c1bf0ad4d0a4802a68bc501106))
* **web:** restyle the app as a dense trading terminal ([7fabc99](https://github.com/Dylan-Burns/keel/commit/7fabc9916969e319abc34f743b3f64f65e5747be))
* **web:** state machine, API client, and the regions of 14.5 ([13912f2](https://github.com/Dylan-Burns/keel/commit/13912f249472f49f2d2f1fdf69fd7248d8ae90fb))
* **web:** static export of the example answers ([e1758b6](https://github.com/Dylan-Burns/keel/commit/e1758b6665871d534baf9646830bd5091bc5a1d9))


### Bug fixes

* **api:** break the import cycle and download models for the e2e job ([25873dd](https://github.com/Dylan-Burns/keel/commit/25873dd85a3e31f8554ad808853f6945a8bbb23f))
* **api:** check the comp set owner in the write transaction ([d94deec](https://github.com/Dylan-Burns/keel/commit/d94deecf06937d7b96a84645bf1a5b828655e754))
* **api:** fail closed on a bad users file and add users remove ([36890bf](https://github.com/Dylan-Burns/keel/commit/36890bf4cc7fd152878428cfdcd201948f29c608))
* **api:** redact key and token values in names, headers, and queries ([2461c14](https://github.com/Dylan-Burns/keel/commit/2461c14d0bb9c75f8d4f9251d104a38c5d7668c2))
* **api:** review findings on the audit trace, gates, and drawer motion ([2d41ebf](https://github.com/Dylan-Burns/keel/commit/2d41ebf05909bc4c96e2ebe8f5753dfe566ea24f))
* **api:** review findings on the breaker probe, budget, and redaction ([dc69c10](https://github.com/Dylan-Burns/keel/commit/dc69c10d01259cab18536dcfc3205750a1dbe51c))
* **api:** review findings on the users file, links, and the principal ([ca5bedb](https://github.com/Dylan-Burns/keel/commit/ca5bedbf9199e11b98cf660062d26643cf4f0111))
* **cache:** codeql notes on the facts prefetch and a test helper ([fb7d6af](https://github.com/Dylan-Burns/keel/commit/fb7d6af6e8800f22ec1eafaea070e749abb1614e))
* **cache:** review findings on the live path, refresh exit, and docs ([a5e5c46](https://github.com/Dylan-Burns/keel/commit/a5e5c46e503924b97f1ac72b8361495cf0718109))
* **cache:** rewarm the demo answer cache for prompt 1.5.1 ([267803e](https://github.com/Dylan-Burns/keel/commit/267803e8eb048d01b9334bfb5d4287ab839271d5))
* **chunker:** review findings on tables, token limits, and parts ([9219ef1](https://github.com/Dylan-Burns/keel/commit/9219ef1e5ba8a9ad339538b597bf673c6f4ff69f))
* **cli:** codeql notes on the report header and the export log test ([9d6c67f](https://github.com/Dylan-Burns/keel/commit/9d6c67f3e2c0ae217a1254221bbcdab2e05da816))
* **cli:** count idle weeks and exclude the votes of left-out users ([2d6c5b1](https://github.com/Dylan-Burns/keel/commit/2d6c5b1a473874c42c83b5ed43b5a2422874944c))
* **cli:** count memo exports in the pilot metrics ([2a0e71d](https://github.com/Dylan-Burns/keel/commit/2a0e71d10e3896383c03e1b04dc5ea701858d08f))
* **cli:** count undated records in the pilot metrics ([c53425d](https://github.com/Dylan-Burns/keel/commit/c53425d60cce7fb751a80280548efea22e74aa73))
* **cli:** read the merged audit, feedback, and refresh formats ([785bc71](https://github.com/Dylan-Burns/keel/commit/785bc71e531e6c00a3f5250905738f08051a4c9e))
* **edgar:** check the peer address after connect ([5e05e3f](https://github.com/Dylan-Burns/keel/commit/5e05e3f3ced124a3c8e7ef3bc04894ea51ced952))
* **edgar:** review findings on S-11, cache writes, and docstrings ([e5676fb](https://github.com/Dylan-Burns/keel/commit/e5676fb78187ec1fb5e493fc9f7f8a9f63ae684a))
* **edgar:** review findings on the add path ([983cbc8](https://github.com/Dylan-Burns/keel/commit/983cbc8d915d83f2767f7905c8583fd143f24b9e))
* **edgar:** review findings on the refresh run ([ebcbbab](https://github.com/Dylan-Burns/keel/commit/ebcbbab7e44396c213be152cfffb9192334cda92))
* **eval:** give the judge the text of fact citations ([a222a84](https://github.com/Dylan-Burns/keel/commit/a222a84cecc2a7ec4edade75cd18b20c4fb4d9c3))
* **eval:** judge each cited chunk as the answer model read it ([22072e3](https://github.com/Dylan-Burns/keel/commit/22072e31c4a5cc6642fd8d598398618128e89e6c))
* **eval:** keep about_keel to unmarked sentences, escape judge tags only ([c48b15d](https://github.com/Dylan-Burns/keel/commit/c48b15d983ea50f6bd8115438a15f390355b53dc))
* **eval:** name the gates in the JSON results ([7c70d16](https://github.com/Dylan-Burns/keel/commit/7c70d16bcfd54006883abc57f86cf00a04c0d07b))
* **eval:** review findings on input errors, grade merge, and fallback ([438a113](https://github.com/Dylan-Burns/keel/commit/438a11342e10127a3630966429c0a6f450c8baa0))
* **eval:** show the judge the filing line of each chunk ([f8fd023](https://github.com/Dylan-Burns/keel/commit/f8fd0231d8474e07a50061d5928cd488de5795a7))
* **export:** codeql findings on asserts, the log line, and xml text ([6f3078a](https://github.com/Dylan-Burns/keel/commit/6f3078aed5a31d9d28994f0438084e654e4dabc8))
* **export:** review findings on the export log ([018b921](https://github.com/Dylan-Burns/keel/commit/018b9216dbbf6f95612c2e3cae119de7a88b8bf7))
* **export:** review findings on the lookup, xml text, and the route ([5768d23](https://github.com/Dylan-Burns/keel/commit/5768d23eb1f1e0ac08a5aee73e985a590eef0a71))
* **index:** review findings on paths, publish, reuse, and versions ([5dff426](https://github.com/Dylan-Burns/keel/commit/5dff4263e7a3285013c646049cc4692573b6beb5))
* **infra:** check the socket peer and redact signed URLs ([c86a1cb](https://github.com/Dylan-Burns/keel/commit/c86a1cb82e91f672cbd1d6c938de7e3cea57937f))
* **infra:** codeql notes on the host test and the version import ([eed79c8](https://github.com/Dylan-Burns/keel/commit/eed79c88ad434a90240033a6dc42809974a68402))
* **infra:** create the backup archive private from the start ([ac254ad](https://github.com/Dylan-Burns/keel/commit/ac254ad80dba62886428e5ad906f17c0a70edf98))
* **infra:** keep index.url unsigned and its secrets out of the logs ([6a33f1c](https://github.com/Dylan-Burns/keel/commit/6a33f1c9529395c2812e9bf3da1c289c777a8d6e))
* **infra:** review findings on bootstrap, backup, and scheduler ([f74787d](https://github.com/Dylan-Burns/keel/commit/f74787dd83747e71436087dd5e9ce576ce599ac6))
* **infra:** review findings on jobs, reload, and backups ([5f7eba0](https://github.com/Dylan-Burns/keel/commit/5f7eba01af2d2e05c776c3058a692f41483ceeea))
* **parser:** read dollar-sign units and keep units lines inside tables ([b596884](https://github.com/Dylan-Burns/keel/commit/b5968847dda4d3e0786018f27cb37b7284c634b5))
* **parser:** review findings on dates, footers, and docs ([20a201a](https://github.com/Dylan-Burns/keel/commit/20a201a02e9c47a884f6876db837c55c1539d710))
* **parser:** strict trust check on the header URL ([4ab886d](https://github.com/Dylan-Burns/keel/commit/4ab886d0446eaba430d7d44040873f133414f7ba))
* **prompt:** review findings on the output mode, calibrate, and docs ([a30270e](https://github.com/Dylan-Burns/keel/commit/a30270ebe1004a4810dae8dd332abd7c5f82a146))
* **provider:** resolve CodeQL findings on asserts and the protocol stub ([b66333f](https://github.com/Dylan-Burns/keel/commit/b66333fe010eac382c3c3f33ff0cd5d1df76216b))
* **provider:** review findings on stream errors, content, and audit ([aaa41dd](https://github.com/Dylan-Burns/keel/commit/aaa41ddcc129ed10dd4e1f2c7213f50bc0da8738))
* **retriever:** demote superseded filings and quarters of a year scope ([0432f30](https://github.com/Dylan-Burns/keel/commit/0432f308855990753e666e77b79691326bfd1935))
* **retriever:** pin the rerank fill and the risk cells after review ([28892a2](https://github.com/Dylan-Burns/keel/commit/28892a2b62e7f5ee931ba259937be86c41f092dd))
* **retriever:** read the latest 10-K first and spend all 80 rerank pairs ([347ea7f](https://github.com/Dylan-Burns/keel/commit/347ea7f274fe128a7bb971c71c558f2004f2be44))
* **retriever:** review findings on quotas, rerank cap, and ordering ([a7287d4](https://github.com/Dylan-Burns/keel/commit/a7287d4b29d6cdd397aed14779789417d4ad15ab))
* **sections:** drop an article between a reference cue and an item label ([f3037eb](https://github.com/Dylan-Burns/keel/commit/f3037eb89bfb55fa56b6d1d45f3aed05bb5a1c7b))
* **stage-01:** review findings on secrets, extraction, and tests ([5588d3a](https://github.com/Dylan-Burns/keel/commit/5588d3a40f7770dccc745c9f7fa62aa388f0c113))
* **stage-16:** harden the preflight checks ([fd77b3c](https://github.com/Dylan-Burns/keel/commit/fd77b3c46d3962920d518ed618ce703bf015de69))
* **understanding:** review findings on scopes, parts, and guards ([3081992](https://github.com/Dylan-Burns/keel/commit/30819922405fb48048909bc94b266fbf2537065b))
* **understanding:** trend for 2 fiscal years, notes for legal questions ([3eabeac](https://github.com/Dylan-Burns/keel/commit/3eabeacc69ce7016b53a708959cab9d97d91efbd))
* **understanding:** weigh business for questions on business segments ([59ac993](https://github.com/Dylan-Burns/keel/commit/59ac993276511d32ccfbba6698db349ac9b088e4))
* **web:** accurate data use statements ([68a4cc4](https://github.com/Dylan-Burns/keel/commit/68a4cc4bddbc0bd3f1633451b99cdfce6c64facd))
* **web:** name the failed action and explain a rejected comp set ([1e6b6d5](https://github.com/Dylan-Burns/keel/commit/1e6b6d52632a4de5ca5475feff9f2ee7687480eb))
* **web:** never ask a question from the url ([2df2f9a](https://github.com/Dylan-Burns/keel/commit/2df2f9aa315ffdd33e1967f903b6b19e169f8464))
* **web:** review findings on the stream end, refresh, and steps ([5328bd9](https://github.com/Dylan-Burns/keel/commit/5328bd9ee707b6e06b2f6c54122ff85e35be1ad9))
* **web:** show the disabled note button without opacity ([3a09eb0](https://github.com/Dylan-Burns/keel/commit/3a09eb0b80ef3dc4049c898656ec800919fd270d))
* **web:** stop the cursor on an error and keep the answer region live ([15d96a2](https://github.com/Dylan-Burns/keel/commit/15d96a25638dadbaf19dec1a96428bd657ed1a3e))
* **web:** stream the answer in stable blocks without layout scaling ([92c37d5](https://github.com/Dylan-Burns/keel/commit/92c37d55cb0b36db6ada6aa5f08d95d703cb3d59))


### Documentation

* **docs:** count the tests of the rebased prompt 1.5.1 branch ([8cae571](https://github.com/Dylan-Burns/keel/commit/8cae5712c6db0ea3182a87dce94b4f7a59149441))
* **docs:** count the tests of the review fixes ([619763f](https://github.com/Dylan-Burns/keel/commit/619763f726d67a7bef206b8226b3741165557b73))
* **docs:** document KEEL_INDEX__URL for the 4 GB host ([474d6c7](https://github.com/Dylan-Burns/keel/commit/474d6c7880316db9e5071b7dd1e9dc04f61d4ed2))
* **docs:** judge context follow-up in the build report and memo ([0a81d39](https://github.com/Dylan-Burns/keel/commit/0a81d39e95dd2258f4f7b6513b7f8a65bc8671b0))
* **docs:** record the prompt 1.5.0 live eval, default stays 1.4.0 ([719ea99](https://github.com/Dylan-Burns/keel/commit/719ea995bae4fe213a070d463e8a995999ff8f26))
* **docs:** record the prompt 1.5.1 live eval, default moves to 1.5.1 ([5bd2bec](https://github.com/Dylan-Burns/keel/commit/5bd2bece5a5cdfe74b726bb8c971cc6b5f984a09))
* **docs:** record the terminal theme and dark mode follow-up ([b328b3b](https://github.com/Dylan-Burns/keel/commit/b328b3b070920d7d92574b32a72685d7c5bdfecc))
* **docs:** retrieval recall follow-up in the build report and memo ([3be6d80](https://github.com/Dylan-Burns/keel/commit/3be6d80d92284b4cc166ee3fbb877619b226034a))
* **docs:** review findings on the judge context follow-up ([5b42f24](https://github.com/Dylan-Burns/keel/commit/5b42f24bce7214130e122cc20b451c653a6eac47))
* **docs:** review findings on the prompt 1.5.1 follow-up ([3a2c6a7](https://github.com/Dylan-Burns/keel/commit/3a2c6a7b37d3b7365d0cf9374c5b3c171160abf6))
* **docs:** review notes on the recall follow-up ([9ea29de](https://github.com/Dylan-Burns/keel/commit/9ea29def350179b1a27112c6606f59cf8b710803))
* **eval:** build report note on table units and the ci answer gates ([83d7793](https://github.com/Dylan-Burns/keel/commit/83d7793b33375c65e31d0e32c536118cfb5aa569))
* **eval:** first report ([e14e951](https://github.com/Dylan-Burns/keel/commit/e14e9516ad25b8b7ead07787527db47de246d3bd))
* **eval:** full live run with judge prompt 1.2.0 ([ba5f65c](https://github.com/Dylan-Burns/keel/commit/ba5f65c62205bb1d8f5b7eb5ecdca81ec302b49a))
* **eval:** report after the fixes ([b612804](https://github.com/Dylan-Burns/keel/commit/b612804009041b9adee937d469d368384910a10f))
* **eval:** report of the live run after the retrieval follow-up ([7e79498](https://github.com/Dylan-Burns/keel/commit/7e79498a0384960b70147f183b31e92fdc1e80e6))
* **eval:** report on index 1.2.0 ([191aedf](https://github.com/Dylan-Burns/keel/commit/191aedf6781bb883e3f6a489139c67571ec70c3d))
* **infra:** move the pilot host to aws t3.large (d-39) ([863b442](https://github.com/Dylan-Burns/keel/commit/863b442c4ed60b6b5acace79abdfbb2171775698))
* **prompt:** prompt log with the before and after ([c800fc8](https://github.com/Dylan-Burns/keel/commit/c800fc8ef900ea14a8740a5e90332bc312ec825e))
* **stage-00:** build report and resolved placeholders ([89a7152](https://github.com/Dylan-Burns/keel/commit/89a7152fe01f119c1a7dd7b3f6dca77d8a6af10f))
* **stage-01:** build report with the corpus facts and A-15 ([3b01b28](https://github.com/Dylan-Burns/keel/commit/3b01b282450a663e6e0ad63f513c7c5bf7e9f0b1))
* **stage-02:** build report with the parse numbers and deviations ([dffaa77](https://github.com/Dylan-Burns/keel/commit/dffaa77e909bf3f3ec39bd77f67135a53493a500))
* **stage-03:** build report with the section and chunk numbers ([d4a2cf3](https://github.com/Dylan-Burns/keel/commit/d4a2cf3087fcf78fd152063fd3f3d57fd54d2acb))
* **stage-04:** build report with the index numbers ([0856e73](https://github.com/Dylan-Burns/keel/commit/0856e73c6a4f1f67e8aca15baac0bfc62ad35a95))
* **stage-05:** build report with the 3 example analyses ([947cf75](https://github.com/Dylan-Burns/keel/commit/947cf75424f88699726f7abdabbd32e81454f3c2))
* **stage-06:** build report with the 3 retrieval plans ([7597d3a](https://github.com/Dylan-Burns/keel/commit/7597d3ab6c436603a4827603f670787d2a428568))
* **stage-07:** prompt log entry 1.0.0 ([5016d52](https://github.com/Dylan-Burns/keel/commit/5016d52b0113042b878a7e68ba5dc92caf5af54f))
* **stage-08:** build report ([c7c969d](https://github.com/Dylan-Burns/keel/commit/c7c969d95604e06da1df0381777da111e8eb14c4))
* **stage-09:** build report ([7359934](https://github.com/Dylan-Burns/keel/commit/735993469c392a56d332d5d54682af1fad3336e1))
* **stage-10:** build report ([2b72bd1](https://github.com/Dylan-Burns/keel/commit/2b72bd14874405f45e092d381088920229e90f99))
* **stage-11:** build report ([0c031af](https://github.com/Dylan-Burns/keel/commit/0c031af69ba7414c1b39f96bf26f77e354891251))
* **stage-11:** review notes and the fallback budget decision ([ed680c8](https://github.com/Dylan-Burns/keel/commit/ed680c8e18770542fd961962afaf0485629aebe4))
* **stage-12:** build report ([5133351](https://github.com/Dylan-Burns/keel/commit/51333512a63794b6f0599014bb57c64a49487b5d))
* **stage-13:** build report ([851793a](https://github.com/Dylan-Burns/keel/commit/851793ad5de66ba2a73f72dfbf9082905b7eb213))
* **stage-14:** build report ([d8d1769](https://github.com/Dylan-Burns/keel/commit/d8d1769efd62c2a8c4e3e93412d2835876debc0d))
* **stage-15:** build report ([2ea642e](https://github.com/Dylan-Burns/keel/commit/2ea642ef0c2c87ada7cebd903cd00405057640fc))
* **stage-15:** performance memo, pushback drills, code walk ([c8931c0](https://github.com/Dylan-Burns/keel/commit/c8931c04e92b61c97338e1c6cca955227255c0db))
* **stage-16:** build report ([ee41ce4](https://github.com/Dylan-Burns/keel/commit/ee41ce48b040f03fe7244dfc77f7b0782ca1c755))
* **stage-16:** rehearsal script and failure drills ([5d10894](https://github.com/Dylan-Burns/keel/commit/5d10894f673c467f05648f5201cf6920b51d8716))
* **stage-16:** static export and draft recording ([0bfa023](https://github.com/Dylan-Burns/keel/commit/0bfa0235f95557400a5a4984208c94988f482b28))
* **stage-16:** static export of the prompt 1.5.1 answers ([7eb7c7b](https://github.com/Dylan-Burns/keel/commit/7eb7c7b654c64fc650783bd7168177dbfe0d5601))
* **stage-17:** build report ([1377c45](https://github.com/Dylan-Burns/keel/commit/1377c451ff262624bae330cde53ba17b6360b0ed))
* **stage-18:** build report ([d7b6d67](https://github.com/Dylan-Burns/keel/commit/d7b6d67fc560bc98897dc238c96c2ea5a1c37206))
* **stage-19:** build report ([b94eff5](https://github.com/Dylan-Burns/keel/commit/b94eff535b7a56124e09d490f4765e383bf8577c))
* **stage-20:** build report ([2b7100e](https://github.com/Dylan-Burns/keel/commit/2b7100edeebf45586874d250ba9053b933ccb2c6))
* **stage-21:** data use page and restore date ([feaaf13](https://github.com/Dylan-Burns/keel/commit/feaaf13cbbd0a1e0d9ca12ae4e97c291e7fc3226))
* **stage-21:** review findings in the build report ([e4b4963](https://github.com/Dylan-Burns/keel/commit/e4b49632352e4d13e2c0cc9c777a66dd5adda1c9))
* **stage-21:** status next stage 22 ([44870c9](https://github.com/Dylan-Burns/keel/commit/44870c9e26eace751f7a748a91a344b2e1aef68c))
* **stage-21:** the private backup archive ([7aedd28](https://github.com/Dylan-Burns/keel/commit/7aedd2803b01b31b98a2a7127796c0ad1486b0cc))
* **stage-22:** build report ([1a6bc87](https://github.com/Dylan-Burns/keel/commit/1a6bc87efcd191627cf5a4edd988e16172efc5ca))
* **stage-22:** fix the backup, legacy user, and heading notes ([d0827ff](https://github.com/Dylan-Burns/keel/commit/d0827ff5e6fc0d57fd711346f4fc80c1d62f8206))
* **stage-22:** order the entries and close the backup gaps ([a2cbdec](https://github.com/Dylan-Burns/keel/commit/a2cbdec4170e407c4507455f1bed0dc0c8bc7d4c))
* **stage-22:** readme numbers from stage 15 and the stage 21 commands ([35bd0f4](https://github.com/Dylan-Burns/keel/commit/35bd0f42a0a776845512d06fa5354f695723d1e4))
* **stage-22:** second rehearsal ([56b3ece](https://github.com/Dylan-Burns/keel/commit/56b3ecebea72285c2e934080afd468644512d2a9))
* **stage-22:** start guide and readme ([52f74c8](https://github.com/Dylan-Burns/keel/commit/52f74c850566d9659d2a6758671389e107764868))
* **stage-22:** status complete ([e09e46d](https://github.com/Dylan-Burns/keel/commit/e09e46d8e884a026a4633837255e067d92819410))
* **stage-22:** the export log ([979a3c0](https://github.com/Dylan-Burns/keel/commit/979a3c062d5f90ac311eabf3392a8c569a7c2e1c))

## [Unreleased]

### Added

- Repository foundation: plan, CLAUDE.md, CI, container, infrastructure, and
  engineering standards.
