# Backend

Python (FastAPI) API server, planned for Milestone 5:
- upload and storage of recorded sessions, accessible only to their authenticated owner, and encrypted at rest;
- HL7 FHIR R4 `Observation` export of the heart rate, with a reference to the recording.

The backend does no signal processing: it stores the results computed by the desktop application.

Design: [`architecture.md`](../docs/regulatory/architecture.md) §6.3. Security: [`cybersecurity.md`](../docs/regulatory/cybersecurity.md).
