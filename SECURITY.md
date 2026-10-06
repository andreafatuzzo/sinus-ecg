# Security policy

Sinus is a personal engineering project, not a medical device (see [`README.md`](README.md)). Security is still part of its design: the threat model, the security controls and the handling of vulnerabilities are described in [`docs/regulatory/cybersecurity.md`](docs/regulatory/cybersecurity.md).

## Supported versions

Only the latest milestone release is maintained.

| Version | Supported |
|---|---|
| Latest milestone release: the most recent `m<N>` or `m<N>.<P>` tag on `main` | Yes |
| Earlier milestone releases | No |
| Branches that are not released (`develop`, feature branches) | No: fixes are made there first and reach `main` with a release |

A fix is released with the next milestone at the latest. A fix for a vulnerability that can affect the safety of a person wearing the device is released before the device is worn again.

## Reporting a vulnerability

Please **do not open a public issue** for a vulnerability in Sinus.

Report it privately through GitHub's private vulnerability reporting: open the **Security** tab of this repository and choose **Report a vulnerability** (<https://github.com/andreafatuzzo/sinus-ecg/security/advisories/new>). Please include:
- the affected part (for example the `dsp` reference pipeline, a script, a workflow) and the version or commit;
- how to reproduce the problem, and what an attacker could achieve;
- any fix or mitigation you suggest.

What happens next:
- the report is triaged within 30 days: whether the vulnerable code can be reached in Sinus, and its effect on security and on safety;
- the fix and its disclosure are coordinated with you. A fixed vulnerability is noted in the pull request that fixes it and in the verification report of the milestone, and a security advisory is published when the vulnerability is in Sinus's own code. You are credited unless you prefer not to be.

## Scope

- **In scope:** the code, scripts and CI workflows of this repository.
- **Third-party components** (Python packages, and later ESP-IDF, Qt and the backend frameworks): please report a vulnerability to the component's maintainers. If you believe it affects Sinus, a private report here is welcome too. Known vulnerabilities in the components that Sinus uses are monitored as described in `cybersecurity.md` §7.
- **Out of scope:** the public reference databases themselves; please report a problem with them to PhysioNet.
