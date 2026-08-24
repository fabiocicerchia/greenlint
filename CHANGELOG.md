# Changelog

## [0.5.0](https://github.com/fabiocicerchia/greenlint/compare/v0.4.0...v0.5.0) (2026-08-24)


### Features

* add .greenlint.toml config for rule disable/ignore ([4f0f56a](https://github.com/fabiocicerchia/greenlint/commit/4f0f56ac7921d387d748fca95e438fd714e4b76b))
* add install.sh one-liner installer ([430ecab](https://github.com/fabiocicerchia/greenlint/commit/430ecabe265de5d733a07fd347ac6869ecd27ec2))
* add pre-commit hook shim and --format github annotations ([45e9bc4](https://github.com/fabiocicerchia/greenlint/commit/45e9bc4f236977189ab232435fa0d82d29e36b56))
* annotate findings with an estimated gCO2e per finding class ([9378051](https://github.com/fabiocicerchia/greenlint/commit/9378051bdaef65122075966ee152605497a12a0f))
* AST-based GL001 busy-loop check for Python ([d0c2195](https://github.com/fabiocicerchia/greenlint/commit/d0c21952c07dda05dee21a2d4e1407d6280425eb))
* expose the scan API editors need ([#46](https://github.com/fabiocicerchia/greenlint/issues/46)) ([b20e6fa](https://github.com/fabiocicerchia/greenlint/commit/b20e6fad42b231ba337020ba40d2795e9bbdaaca))
* **rules:** add GL009-GL018 from the greenops sustainability book ([2be2efb](https://github.com/fabiocicerchia/greenlint/commit/2be2efb6bffcd98f7ffcec2cbd648aa46924211f))
* **rules:** add GL019-GL029 — loop anti-patterns and cloud-cost/caching rules ([459f56b](https://github.com/fabiocicerchia/greenlint/commit/459f56bed8da0d4d1528d592de710f4d1204e973))
* **rules:** add GL030-GL034, OpenTofu support, and Kubernetes CronJob coverage ([9f1073d](https://github.com/fabiocicerchia/greenlint/commit/9f1073d357d9df9d5772b2318d09f76c78be24a7))
* **rules:** add GL035-GL038 and broaden polling/SELECT-* detection cross-language ([09a1890](https://github.com/fabiocicerchia/greenlint/commit/09a18905d21a8d2a218298701caee46c58f97d45))
* **rules:** three or more rules each for C#, Kotlin, Swift and Ruby ([#47](https://github.com/fabiocicerchia/greenlint/issues/47)) ([43c8ec1](https://github.com/fabiocicerchia/greenlint/commit/43c8ec19b9523c4935817ae328702180130cc342))


### Bug Fixes

* classify tuple-unpacked scalars in GL007 ([#43](https://github.com/fabiocicerchia/greenlint/issues/43)) ([6dda8c1](https://github.com/fabiocicerchia/greenlint/commit/6dda8c1799be0133a1b4f115b3440c2958bafc0d))
* correct the CO2e estimates, which were fiction on most rules ([#28](https://github.com/fabiocicerchia/greenlint/issues/28)) ([1433925](https://github.com/fabiocicerchia/greenlint/commit/1433925fee4e745fdcc99131ca9c5c16c882a28c))
* let greenlint own the finding order and the rule anchors ([#54](https://github.com/fabiocicerchia/greenlint/issues/54)) ([5c0709f](https://github.com/fabiocicerchia/greenlint/commit/5c0709f6892a0c0f2f8f2c307f43e08d2d114fb0))
* **pre-commit:** stop check-yaml failing on Helm templates and multi-doc manifests ([26bdf1d](https://github.com/fabiocicerchia/greenlint/commit/26bdf1db4603e85e6ddf553c83940f74dabe4ee8))
* restore executable bit and satisfy newer ruff rules ([#11](https://github.com/fabiocicerchia/greenlint/issues/11)) ([4e13677](https://github.com/fabiocicerchia/greenlint/commit/4e136774c112e2e0495c62e4ee0b0b05a7205ee8))
* security and code-quality findings ([#35](https://github.com/fabiocicerchia/greenlint/issues/35)) ([f1890f2](https://github.com/fabiocicerchia/greenlint/commit/f1890f2fcec64e0a06c84377ca18606f00d3f006))
* **security:** skip the SARIF upload on private repos ([d33314a](https://github.com/fabiocicerchia/greenlint/commit/d33314af2a69d184e735e57d9ac383fce6e4943a))
* stop scanning virtualenvs, and make the extension explain itself ([#56](https://github.com/fabiocicerchia/greenlint/issues/56)) ([978680d](https://github.com/fabiocicerchia/greenlint/commit/978680d4aeb3751e1de0f0cada163c4c900011ea))


### Documentation

* add GitHub Pages site, trim completed roadmap items from README ([fa6cb8d](https://github.com/fabiocicerchia/greenlint/commit/fa6cb8d536935a20d002a26a40f9ca2ff6dbd9cc))
* add missing README badges ([ec4c195](https://github.com/fabiocicerchia/greenlint/commit/ec4c1957a1d7392e1ec2a9c848cdc512f38d94c3))
* add rules.md reference and expand architecture notes ([221545e](https://github.com/fabiocicerchia/greenlint/commit/221545ee6a075c573e41015c9d9f7fc42990f09a))
* correct three rule descriptions that no longer match the code ([#31](https://github.com/fabiocicerchia/greenlint/issues/31)) ([279db17](https://github.com/fabiocicerchia/greenlint/commit/279db1705b1f079762f0f84689d1aa2a6b9ab422))
* install the VS Code extension from the marketplaces ([#52](https://github.com/fabiocicerchia/greenlint/issues/52)) ([978b856](https://github.com/fabiocicerchia/greenlint/commit/978b8563d64ca5d45c8a57e5d5096f790eb40117))
* remove the broken FOSSA badge ([a5ff431](https://github.com/fabiocicerchia/greenlint/commit/a5ff43144e02a28aa6974c02c356eaf203b729f2))

## [0.4.0](https://github.com/fabiocicerchia/greenlint/compare/v0.3.0...v0.4.0) (2026-08-24)


### Features

* **rules:** three or more rules each for C#, Kotlin, Swift and Ruby ([#47](https://github.com/fabiocicerchia/greenlint/issues/47)) ([43c8ec1](https://github.com/fabiocicerchia/greenlint/commit/43c8ec19b9523c4935817ae328702180130cc342))


### Bug Fixes

* let greenlint own the finding order and the rule anchors ([#54](https://github.com/fabiocicerchia/greenlint/issues/54)) ([5c0709f](https://github.com/fabiocicerchia/greenlint/commit/5c0709f6892a0c0f2f8f2c307f43e08d2d114fb0))
* stop scanning virtualenvs, and make the extension explain itself ([#56](https://github.com/fabiocicerchia/greenlint/issues/56)) ([978680d](https://github.com/fabiocicerchia/greenlint/commit/978680d4aeb3751e1de0f0cada163c4c900011ea))


### Documentation

* install the VS Code extension from the marketplaces ([#52](https://github.com/fabiocicerchia/greenlint/issues/52)) ([978b856](https://github.com/fabiocicerchia/greenlint/commit/978b8563d64ca5d45c8a57e5d5096f790eb40117))

## [0.3.0](https://github.com/fabiocicerchia/greenlint/compare/v0.2.0...v0.3.0) (2026-08-18)


### Features

* add .greenlint.toml config for rule disable/ignore ([4f0f56a](https://github.com/fabiocicerchia/greenlint/commit/4f0f56ac7921d387d748fca95e438fd714e4b76b))
* add install.sh one-liner installer ([430ecab](https://github.com/fabiocicerchia/greenlint/commit/430ecabe265de5d733a07fd347ac6869ecd27ec2))
* add pre-commit hook shim and --format github annotations ([45e9bc4](https://github.com/fabiocicerchia/greenlint/commit/45e9bc4f236977189ab232435fa0d82d29e36b56))
* annotate findings with an estimated gCO2e per finding class ([9378051](https://github.com/fabiocicerchia/greenlint/commit/9378051bdaef65122075966ee152605497a12a0f))
* AST-based GL001 busy-loop check for Python ([d0c2195](https://github.com/fabiocicerchia/greenlint/commit/d0c21952c07dda05dee21a2d4e1407d6280425eb))
* expose the scan API editors need ([#46](https://github.com/fabiocicerchia/greenlint/issues/46)) ([b20e6fa](https://github.com/fabiocicerchia/greenlint/commit/b20e6fad42b231ba337020ba40d2795e9bbdaaca))
* **rules:** add GL009-GL018 from the greenops sustainability book ([2be2efb](https://github.com/fabiocicerchia/greenlint/commit/2be2efb6bffcd98f7ffcec2cbd648aa46924211f))
* **rules:** add GL019-GL029 — loop anti-patterns and cloud-cost/caching rules ([459f56b](https://github.com/fabiocicerchia/greenlint/commit/459f56bed8da0d4d1528d592de710f4d1204e973))
* **rules:** add GL030-GL034, OpenTofu support, and Kubernetes CronJob coverage ([9f1073d](https://github.com/fabiocicerchia/greenlint/commit/9f1073d357d9df9d5772b2318d09f76c78be24a7))
* **rules:** add GL035-GL038 and broaden polling/SELECT-* detection cross-language ([09a1890](https://github.com/fabiocicerchia/greenlint/commit/09a18905d21a8d2a218298701caee46c58f97d45))


### Bug Fixes

* classify tuple-unpacked scalars in GL007 ([#43](https://github.com/fabiocicerchia/greenlint/issues/43)) ([6dda8c1](https://github.com/fabiocicerchia/greenlint/commit/6dda8c1799be0133a1b4f115b3440c2958bafc0d))
* correct the CO2e estimates, which were fiction on most rules ([#28](https://github.com/fabiocicerchia/greenlint/issues/28)) ([1433925](https://github.com/fabiocicerchia/greenlint/commit/1433925fee4e745fdcc99131ca9c5c16c882a28c))
* **pre-commit:** stop check-yaml failing on Helm templates and multi-doc manifests ([26bdf1d](https://github.com/fabiocicerchia/greenlint/commit/26bdf1db4603e85e6ddf553c83940f74dabe4ee8))
* restore executable bit and satisfy newer ruff rules ([#11](https://github.com/fabiocicerchia/greenlint/issues/11)) ([4e13677](https://github.com/fabiocicerchia/greenlint/commit/4e136774c112e2e0495c62e4ee0b0b05a7205ee8))
* security and code-quality findings ([#35](https://github.com/fabiocicerchia/greenlint/issues/35)) ([f1890f2](https://github.com/fabiocicerchia/greenlint/commit/f1890f2fcec64e0a06c84377ca18606f00d3f006))
* **security:** skip the SARIF upload on private repos ([d33314a](https://github.com/fabiocicerchia/greenlint/commit/d33314af2a69d184e735e57d9ac383fce6e4943a))


### Documentation

* add GitHub Pages site, trim completed roadmap items from README ([fa6cb8d](https://github.com/fabiocicerchia/greenlint/commit/fa6cb8d536935a20d002a26a40f9ca2ff6dbd9cc))
* add missing README badges ([ec4c195](https://github.com/fabiocicerchia/greenlint/commit/ec4c1957a1d7392e1ec2a9c848cdc512f38d94c3))
* add rules.md reference and expand architecture notes ([221545e](https://github.com/fabiocicerchia/greenlint/commit/221545ee6a075c573e41015c9d9f7fc42990f09a))
* correct three rule descriptions that no longer match the code ([#31](https://github.com/fabiocicerchia/greenlint/issues/31)) ([279db17](https://github.com/fabiocicerchia/greenlint/commit/279db1705b1f079762f0f84689d1aa2a6b9ab422))
* remove the broken FOSSA badge ([a5ff431](https://github.com/fabiocicerchia/greenlint/commit/a5ff43144e02a28aa6974c02c356eaf203b729f2))

## [0.2.0](https://github.com/fabiocicerchia/greenlint/compare/v0.1.5...v0.2.0) (2026-08-18)


### Features

* expose the scan API editors need ([#46](https://github.com/fabiocicerchia/greenlint/issues/46)) ([b20e6fa](https://github.com/fabiocicerchia/greenlint/commit/b20e6fad42b231ba337020ba40d2795e9bbdaaca))

## [0.1.5](https://github.com/fabiocicerchia/greenlint/compare/v0.1.4...v0.1.5) (2026-08-15)


### Bug Fixes

* classify tuple-unpacked scalars in GL007 ([#43](https://github.com/fabiocicerchia/greenlint/issues/43)) ([6dda8c1](https://github.com/fabiocicerchia/greenlint/commit/6dda8c1799be0133a1b4f115b3440c2958bafc0d))

## [0.1.4](https://github.com/fabiocicerchia/greenlint/compare/v0.1.3...v0.1.4) (2026-08-13)


### Bug Fixes

* security and code-quality findings ([#35](https://github.com/fabiocicerchia/greenlint/issues/35)) ([f1890f2](https://github.com/fabiocicerchia/greenlint/commit/f1890f2fcec64e0a06c84377ca18606f00d3f006))

## [0.1.3](https://github.com/fabiocicerchia/greenlint/compare/v0.1.2...v0.1.3) (2026-08-10)


### Documentation

* correct three rule descriptions that no longer match the code ([#31](https://github.com/fabiocicerchia/greenlint/issues/31)) ([279db17](https://github.com/fabiocicerchia/greenlint/commit/279db1705b1f079762f0f84689d1aa2a6b9ab422))

## [0.1.2](https://github.com/fabiocicerchia/greenlint/compare/v0.1.1...v0.1.2) (2026-08-10)


### Bug Fixes

* correct the CO2e estimates, which were fiction on most rules ([#28](https://github.com/fabiocicerchia/greenlint/issues/28)) ([1433925](https://github.com/fabiocicerchia/greenlint/commit/1433925fee4e745fdcc99131ca9c5c16c882a28c))

## [0.1.1](https://github.com/fabiocicerchia/greenlint/compare/v0.1.0...v0.1.1) (2026-08-06)


### Bug Fixes

* **pre-commit:** stop check-yaml failing on Helm templates and multi-doc manifests ([26bdf1d](https://github.com/fabiocicerchia/greenlint/commit/26bdf1db4603e85e6ddf553c83940f74dabe4ee8))
* **security:** skip the SARIF upload on private repos ([d33314a](https://github.com/fabiocicerchia/greenlint/commit/d33314af2a69d184e735e57d9ac383fce6e4943a))

## Changelog

This file is generated by [release-please](.github/workflows/release.yml) from
Conventional Commit messages. Don't edit it by hand.
