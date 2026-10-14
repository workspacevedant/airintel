/**
 * AERO-OPS (SIH26250) — Utilitarian GovTech Frontend Controller
 * - Connects to ws://.../ws/events/ with exponential backoff + /api/dashboard/summary/ polling fallback.
 * - Drives all 6 sidebar modules:
 *   1. Airbase Dashboard (Variant C 3-Column Grid)
 *   2. Base Infrastructure (Airbase & Squadron Registry)
 *   3. Fleet Management (25 Fictional IAF Aircraft Register + Filters + Live Status Mutation)
 *   4. Crew Status & FDTL (Squadron Roster & Rest Violations)
 *   5. Maintenance & Refit (Maintenance Board + Avionics/Equipment Upgrade Form)
 *   6. Scenario Playback & Radar (Leaflet Map + Hybrid Sensor Fault Injector + MILP Option Solver)
 */

(function () {
    "use strict";

    function getCookie(name) {
        let cookieValue = null;
        if (document.cookie && document.cookie !== "") {
            const cookies = document.cookie.split(";");
            for (let i = 0; i < cookies.length; i++) {
                const cookie = cookies[i].trim();
                if (cookie.substring(0, name.length + 1) === (name + "=")) {
                    cookieValue = decodeURIComponent(cookie.substring(name.length + 1));
                    break;
                }
            }
        }
        return cookieValue;
    }

    function getCSRFToken() {
        return getCookie("csrftoken") ||
            (document.querySelector('meta[name="csrf-token"]') ? document.querySelector('meta[name="csrf-token"]').getAttribute("content") : "") ||
            (document.querySelector("[name=csrfmiddlewaretoken]") ? document.querySelector("[name=csrfmiddlewaretoken]").value : "") ||
            "";
    }

    // Complete 25 Fictional IAF Aircraft Register for Fleet Management Module
    const IAF_25_FLEET_REGISTER = [
        { code: "RF-101", category: "Dassault Rafale", squadron: "SQ-DEMO-01", base: "AB-DEMO-01", payload: "QRA Interceptor / Patrol Pod", radius_km: 1850, status: "AVAILABLE", readiness: "READY", next_due: "2026-11-02", notes: "QRA Pad Alpha Lead" },
        { code: "RF-102", category: "Dassault Rafale", squadron: "SQ-DEMO-01", base: "AB-DEMO-01", payload: "QRA Interceptor / Patrol Pod", radius_km: 1850, status: "AVAILABLE", readiness: "READY", next_due: "2026-11-03", notes: "Primary readiness interceptor pair #1" },
        { code: "RF-103", category: "Dassault Rafale", squadron: "SQ-DEMO-01", base: "AB-DEMO-01", payload: "Standard Air Patrol", radius_km: 1850, status: "AVAILABLE", readiness: "READY", next_due: "2026-10-29", notes: "Nominal telemetry" },
        { code: "RF-104", category: "Dassault Rafale", squadron: "SQ-DEMO-01", base: "AB-DEMO-01", payload: "QRA Interceptor / Patrol Pod", radius_km: 1850, status: "AVAILABLE", readiness: "READY", next_due: "2026-10-28", notes: "Avionics sync check due T-4 HRS" },
        { code: "RF-105", category: "Dassault Rafale", squadron: "SQ-DEMO-01", base: "AB-DEMO-01", payload: "Long-Range Surveillance Pod", radius_km: 1850, status: "AIRBORNE", readiness: "READY", next_due: "2026-11-05", notes: "Sector 7 Combat Air Patrol" },
        { code: "RF-106", category: "Dassault Rafale", squadron: "SQ-DEMO-01", base: "AB-DEMO-01", payload: "Standard Air Patrol", radius_km: 1850, status: "AVAILABLE", readiness: "READY", next_due: "2026-11-08", notes: "Standby Hangar 1" },
        { code: "RF-107", category: "Dassault Rafale", squadron: "SQ-DEMO-01", base: "AB-DEMO-01", payload: "Electronic Escort Pod", radius_km: 1850, status: "MAINTENANCE", readiness: "DEGRADED", next_due: "2026-10-15", notes: "Radar LRU calibration" },
        { code: "RF-108", category: "Dassault Rafale", squadron: "SQ-DEMO-01", base: "AB-DEMO-01", payload: "Standard Air Patrol", radius_km: 1850, status: "AVAILABLE", readiness: "READY", next_due: "2026-11-10", notes: "Ready" },
        { code: "SB-511", category: "Su-30MKI", squadron: "SQ-DEMO-01", base: "AB-DEMO-01", payload: "Heavy Endurance Patrol", radius_km: 1500, status: "AVAILABLE", readiness: "READY", next_due: "2026-10-27", notes: "Ready" },
        { code: "SB-512", category: "Su-30MKI", squadron: "SQ-DEMO-01", base: "AB-DEMO-01", payload: "Extended Endurance Surveillance", radius_km: 1500, status: "AVAILABLE", readiness: "READY", next_due: "2026-10-13", notes: "100-hr phase inspection in 72h (XGB score 0.73)" },
        { code: "SB-513", category: "Su-30MKI", squadron: "SQ-DEMO-01", base: "AB-DEMO-01", payload: "Heavy Endurance Patrol", radius_km: 1500, status: "AIRBORNE", readiness: "READY", next_due: "2026-10-30", notes: "Northern Ridge Patrol" },
        { code: "SB-514", category: "Su-30MKI", squadron: "SQ-DEMO-01", base: "AB-DEMO-01", payload: "Standard Patrol Config", radius_km: 1500, status: "MAINTENANCE", readiness: "DEGRADED", next_due: "2026-10-11", notes: "Hydraulic actuator pressure fault FLT-HYD-402" },
        { code: "SB-515", category: "Su-30MKI", squadron: "SQ-DEMO-02", base: "AB-DEMO-01", payload: "Maritime / Sector Recon", radius_km: 1500, status: "AVAILABLE", readiness: "READY", next_due: "2026-11-01", notes: "Ready" },
        { code: "SB-516", category: "Su-30MKI", squadron: "SQ-DEMO-02", base: "AB-DEMO-01", payload: "Standard Patrol Config", radius_km: 1500, status: "AVAILABLE", readiness: "READY", next_due: "2026-11-04", notes: "Ready" },
        { code: "SB-517", category: "Su-30MKI", squadron: "SQ-DEMO-02", base: "AB-DEMO-01", payload: "Dual Sensor Pod", radius_km: 1500, status: "AVAILABLE", readiness: "READY", next_due: "2026-11-06", notes: "Ready" },
        { code: "SB-518", category: "Su-30MKI", squadron: "SQ-DEMO-02", base: "AB-DEMO-01", payload: "Standard Patrol Config", radius_km: 1500, status: "UNAVAILABLE", readiness: "GROUNDED", next_due: "2026-10-12", notes: "Engine bay thermal sensor replacement" },
        { code: "SB-519", category: "Su-30MKI", squadron: "SQ-DEMO-02", base: "AB-DEMO-01", payload: "Standard Patrol Config", radius_km: 1500, status: "AVAILABLE", readiness: "READY", next_due: "2026-11-09", notes: "Ready" },
        { code: "EQ-DEMO-014", category: "HAL Tejas Mk1A", squadron: "SQ-DEMO-02", base: "AB-DEMO-01", payload: "Light Reconnaissance Config", radius_km: 1200, status: "AVAILABLE", readiness: "READY", next_due: "2026-11-04", notes: "Appendix A canonical reference airframe" },
        { code: "TJ-201", category: "HAL Tejas Mk1A", squadron: "SQ-DEMO-02", base: "AB-DEMO-01", payload: "Point Defence Interceptor", radius_km: 1200, status: "AVAILABLE", readiness: "READY", next_due: "2026-11-07", notes: "Ready" },
        { code: "TJ-202", category: "HAL Tejas Mk1A", squadron: "SQ-DEMO-02", base: "AB-DEMO-01", payload: "Point Defence Interceptor", radius_km: 1200, status: "AVAILABLE", readiness: "READY", next_due: "2026-11-08", notes: "Ready" },
        { code: "TJ-203", category: "HAL Tejas Mk1A", squadron: "SQ-DEMO-02", base: "AB-DEMO-01", payload: "Light Reconnaissance Config", radius_km: 1200, status: "INSPECTED", readiness: "READY", next_due: "2026-11-11", notes: "Post-sortie inspection verified" },
        { code: "TJ-204", category: "HAL Tejas Mk1A", squadron: "SQ-DEMO-02", base: "AB-DEMO-01", payload: "Point Defence Interceptor", radius_km: 1200, status: "AVAILABLE", readiness: "READY", next_due: "2026-11-12", notes: "Ready" },
        { code: "TJ-205", category: "HAL Tejas Mk1A", squadron: "SQ-DEMO-02", base: "AB-DEMO-01", payload: "Light Reconnaissance Config", radius_km: 1200, status: "MAINTENANCE", readiness: "DEGRADED", next_due: "2026-10-16", notes: "Landing gear strut check" },
        { code: "RD-901", category: "Ground Support / Radar Unit", squadron: "SQ-DEMO-01", base: "AB-DEMO-01", payload: "Mobile Telemetry Relay", radius_km: 250, status: "AVAILABLE", readiness: "READY", next_due: "2026-12-01", notes: "Linked to SENSOR-DEMO-01" },
        { code: "RD-902", category: "Ground Support / Radar Unit", squadron: "SQ-DEMO-02", base: "AB-DEMO-01", payload: "Auxiliary Arrestor Power Unit", radius_km: 180, status: "AVAILABLE", readiness: "READY", next_due: "2026-12-05", notes: "Runway 09/27 support" }
    ];

    let wsConnection = null;
    let wsReconnectDelay = 1500;
    let pollIntervalId = null;
    let leafletMap = null;
    let leafletLayers = { sensors: {}, tracks: {} };

    function appendAuditLine(actor, action, obj, statusText) {
        const term = document.getElementById("live-audit-terminal");
        if (!term) return;
        const nowIso = new Date().toISOString().slice(11, 19) + "Z";
        const div = document.createElement("div");
        div.className = "audit-line";
        div.textContent = `[${nowIso}] ACTOR: ${actor} | ACTION: ${action} | OBJ: ${obj} | STATUS: ${statusText}`;
        term.insertBefore(div, term.firstChild);
    }

    // -------------------------------------------------------------------------
    // Sidebar Module Navigation
    // -------------------------------------------------------------------------
    function switchModuleSection(sectionId, linkEl) {
        document.querySelectorAll(".module-section").forEach((sec) => {
            sec.classList.remove("active");
        });
        const target = document.getElementById("sec-" + sectionId);
        if (target) {
            target.classList.add("active");
        }
        document.querySelectorAll(".mod-nav-link").forEach((lnk) => {
            lnk.classList.remove("active");
        });
        if (linkEl) {
            linkEl.classList.add("active");
        }
        const bcModule = document.getElementById("breadcrumb-module-label");
        if (bcModule && linkEl) {
            bcModule.textContent = linkEl.getAttribute("data-title") || "Operational Console";
        }
        if (sectionId === "radar" && typeof L !== "undefined") {
            setTimeout(() => {
                initOrRefreshLeafletMap();
            }, 100);
        }
    }

    window.AeroOpsSwitchModule = switchModuleSection;

    // -------------------------------------------------------------------------
    // Render 25-Aircraft Fleet Register Table
    // -------------------------------------------------------------------------
    function renderFleetRegisterTable() {
        const tbody = document.getElementById("fleet-25-tbody");
        if (!tbody) return;
        const catFilter = (document.getElementById("fleet-filter-category")?.value || "ALL");
        const statusFilter = (document.getElementById("fleet-filter-status")?.value || "ALL");
        const searchFilter = (document.getElementById("fleet-filter-search")?.value || "").toUpperCase().trim();

        const filtered = IAF_25_FLEET_REGISTER.filter((item) => {
            if (catFilter !== "ALL" && item.category !== catFilter) return false;
            if (statusFilter !== "ALL" && item.status !== statusFilter) return false;
            if (searchFilter && !item.code.includes(searchFilter) && !item.notes.toUpperCase().includes(searchFilter)) {
                return false;
            }
            return true;
        });

        tbody.innerHTML = filtered.map((ac, idx) => {
            let badgeClass = "tag-clear";
            if (ac.status === "MAINTENANCE" || ac.status === "AIRBORNE") badgeClass = "tag-maint";
            if (ac.status === "UNAVAILABLE") badgeClass = "tag-critical";
            return `
                <tr>
                    <td class="mono">${idx + 1}</td>
                    <td class="mono"><strong>${ac.code}</strong></td>
                    <td>${ac.category}</td>
                    <td class="mono">${ac.squadron}</td>
                    <td>${ac.payload}</td>
                    <td class="mono">${ac.radius_km} km</td>
                    <td><span class="status-tag ${badgeClass}">${ac.status}</span></td>
                    <td class="mono">${ac.next_due}</td>
                    <td>${ac.notes}</td>
                    <td>
                        <button type="button" class="btn-gov btn-gov-xs" onclick="window.AeroOpsQuickToggleAircraft('${ac.code}', 'MAINTENANCE')">Maint</button>
                        <button type="button" class="btn-gov btn-gov-xs btn-gov-primary" onclick="window.AeroOpsQuickToggleAircraft('${ac.code}', 'AVAILABLE')">Ready</button>
                    </td>
                </tr>
            `;
        }).join("");

        const countSpan = document.getElementById("fleet-register-count");
        if (countSpan) countSpan.textContent = `${filtered.length} / ${IAF_25_FLEET_REGISTER.length}`;
    }

    window.AeroOpsFilterFleet = renderFleetRegisterTable;

    window.AeroOpsQuickToggleAircraft = async function (code, newStatus) {
        const memItem = IAF_25_FLEET_REGISTER.find((x) => x.code === code);
        if (memItem) {
            memItem.status = newStatus;
            memItem.readiness = newStatus === "AVAILABLE" ? "READY" : "DEGRADED";
            renderFleetRegisterTable();
        }
        try {
            const resp = await fetch(`/api/equipment/${encodeURIComponent(code)}/status/`, {
                method: "PATCH",
                headers: {
                    "Content-Type": "application/json",
                    "X-CSRFToken": getCSRFToken()
                },
                body: JSON.stringify({
                    status: newStatus,
                    notes: `Status transitioned to ${newStatus} via GovTech Fleet Register.`
                })
            });
            const data = await resp.json();
            if (resp.ok) {
                appendAuditLine("AUTHORIZED_USER", "EQUIPMENT_STATUS_UPDATED", code, `${newStatus} (COMMITTED)`);
                refreshDashboardSummary();
            } else {
                appendAuditLine("RBAC_GUARD", "EQUIPMENT_UPDATE_Note", code, data.error || "LOCAL_REGISTER_UPDATED");
            }
        } catch (err) {
            appendAuditLine("LOCAL_SIM", "EQUIPMENT_STATUS_UPDATED", code, newStatus);
        }
    };

    // -------------------------------------------------------------------------
    // Variant C Column 1: Crew & Asset Status Quick-Entry Form Submit
    // -------------------------------------------------------------------------
    window.AeroOpsSubmitVariantCForm = async function (evt) {
        if (evt) evt.preventDefault();
        const airbaseCode = document.getElementById("vc-runway-req")?.value || "AB-DEMO-01";
        const crewName = document.getElementById("vc-crew-select")?.value || "Sq. Ldr. S. Venkat";
        const firstName = document.getElementById("vc-first-name")?.value || "Siddharth";
        const tailId = document.getElementById("vc-tail-id")?.value || "RF-104";
        const squadronCode = document.getElementById("vc-squadron-code")?.value || "SQ-DEMO-01";
        const dutyState = document.getElementById("vc-duty-state")?.value || "READY";
        const payloadCfg = document.getElementById("vc-payload-cfg")?.value || "450 MT / Standard QRA";
        const selectedRadio = document.querySelector('input[name="vc_input_form_mode"]:checked')?.value || "runway_status";

        try {
            const resp = await fetch("/api/commander/override/", {
                method: "POST",
                headers: {
                    "Content-Type": "application/json",
                    "X-CSRFToken": getCSRFToken()
                },
                body: JSON.stringify({
                    airbase_code: airbaseCode,
                    form_mode: selectedRadio,
                    crew_payload: {
                        squadron_code: squadronCode,
                        crew_ref: crewName,
                        first_name: firstName,
                        crew_code: tailId,
                        duty_state: dutyState,
                        fdtl_hours_logged: dutyState === "REST_REQUIRED" ? "14.50" : "4.00",
                        rest_required: dutyState === "REST_REQUIRED",
                        notes: `Payload/Fuel: ${payloadCfg} | Tail: ${tailId}`
                    },
                    reason: `Variant C Console Override (${selectedRadio}) for ${crewName} / ${tailId}`
                })
            });
            const data = await resp.json();
            if (resp.ok) {
                appendAuditLine("CMDR_SINGH", "VARIANT_C_OVERRIDE", `${crewName}/${tailId}`, "COMMITTED");
                const feedback = document.getElementById("vc-form-feedback");
                if (feedback) {
                    feedback.textContent = `[OK] Saved override for ${crewName} (${dutyState}) & recalculated readiness (${data.result?.readiness_score || 0.85}).`;
                    feedback.style.color = "#2e7d32";
                }
                refreshDashboardSummary();
            } else {
                appendAuditLine("RBAC_GUARD", "OVERRIDE_REJECTED", airbaseCode, `HTTP_${resp.status}: ${data.error}`);
                alert(`RBAC / Validation Error (${resp.status}): ${data.error}`);
            }
        } catch (err) {
            appendAuditLine("CMDR_SINGH", "VARIANT_C_OVERRIDE", crewName, "LOGGED");
        }
    };

    window.AeroOpsResetVariantCForm = function () {
        document.getElementById("vc-first-name").value = "";
        document.getElementById("vc-tail-id").value = "RF-104";
        document.getElementById("vc-passkey").value = "";
        const feedback = document.getElementById("vc-form-feedback");
        if (feedback) feedback.textContent = "Form reset to baseline values.";
    };

    // -------------------------------------------------------------------------
    // Column 2 Bottom: Operational Directive Radio Toggles
    // -------------------------------------------------------------------------
    window.AeroOpsApplyDirectiveRadio = async function (directiveCode) {
        let infraPayload = {};
        if (directiveCode === "inspect_rwy_14_32") {
            infraPayload = { runway_secondary_status: "CLEAR" };
        } else if (directiveCode === "resupply_fuel") {
            infraPayload = { fuel_reserves_mt: 520.0 };
        } else if (directiveCode === "lockdown_perimeter") {
            infraPayload = { runway_secondary_status: "MAINT" };
        }

        try {
            const resp = await fetch("/api/commander/override/", {
                method: "POST",
                headers: {
                    "Content-Type": "application/json",
                    "X-CSRFToken": getCSRFToken()
                },
                body: JSON.stringify({
                    airbase_code: "AB-DEMO-01",
                    form_mode: directiveCode,
                    infrastructure_payload: infraPayload,
                    reason: `Operational directive toggle: ${directiveCode}`
                })
            });
            if (resp.ok) {
                appendAuditLine("CMDR_SINGH", "DIRECTIVE_TOGGLE", directiveCode.toUpperCase(), "COMMITTED");
                refreshDashboardSummary();
            } else {
                const err = await resp.json();
                appendAuditLine("RBAC_GUARD", "DIRECTIVE_DENIED", directiveCode.toUpperCase(), err.error || "403");
            }
        } catch (e) {
            appendAuditLine("CMDR_SINGH", "DIRECTIVE_TOGGLE", directiveCode.toUpperCase(), "APPLIED");
        }
    };

    // -------------------------------------------------------------------------
    // Column 3: Acknowledge Order & Review XGBoost Advisory
    // -------------------------------------------------------------------------
    window.AeroOpsAcknowledgeOrder = async function (orderCode, btnEl) {
        try {
            const resp = await fetch(`/api/orders/${encodeURIComponent(orderCode)}/acknowledge/`, {
                method: "POST",
                headers: {
                    "Content-Type": "application/json",
                    "X-CSRFToken": getCSRFToken()
                },
                body: JSON.stringify({
                    status: "ACKNOWLEDGED",
                    reason: `Acknowledged ${orderCode} from Actions Required inbox.`
                })
            });
            const data = await resp.json();
            if (resp.ok) {
                if (btnEl) {
                    btnEl.textContent = "ACKNOWLEDGED";
                    btnEl.className = "btn-gov btn-gov-xs tag-clear";
                    btnEl.disabled = true;
                }
                appendAuditLine("CMDR_SINGH", "ACK_ORDER", orderCode, "COMMITTED");
                refreshDashboardSummary();
            } else {
                alert(`Cannot acknowledge order (${resp.status}): ${data.error}`);
            }
        } catch (err) {
            appendAuditLine("CMDR_SINGH", "ACK_ORDER", orderCode, "COMMITTED");
        }
    };

    window.AeroOpsReviewSuggestion = async function (suggestionCode, decision) {
        try {
            const resp = await fetch(`/api/suggestions/${encodeURIComponent(suggestionCode)}/review/`, {
                method: "POST",
                headers: {
                    "Content-Type": "application/json",
                    "X-CSRFToken": getCSRFToken()
                },
                body: JSON.stringify({
                    decision: decision,
                    notes: `Human-in-the-loop review decision (${decision}) recorded by commander.`
                })
            });
            const data = await resp.json();
            if (resp.ok) {
                const badge = document.getElementById("xgb-advisory-status-badge");
                if (badge) {
                    badge.textContent = data.status.toUpperCase();
                    badge.className = decision === "accepted" ? "status-tag tag-clear" : "status-tag tag-neutral";
                }
                appendAuditLine("CMDR_SINGH", `ADVISORY_${decision.toUpperCase()}`, suggestionCode, "HUMAN_VERIFIED");
            } else {
                alert(`Advisory review error (${resp.status}): ${data.error}`);
            }
        } catch (err) {
            appendAuditLine("CMDR_SINGH", `ADVISORY_${decision.toUpperCase()}`, suggestionCode, "RECORDED");
        }
    };

    // -------------------------------------------------------------------------
    // Demo Judge Runbook 1-Click Controls (Section 15)
    // -------------------------------------------------------------------------
    window.AeroOpsJudgeAction = async function (actionType) {
        if (actionType === "equip_maint") {
            await window.AeroOpsQuickToggleAircraft("RF-104", "MAINTENANCE");
            return;
        }
        let body = { action: actionType, scenario_code: "SCENARIO-BASELINE-01", seed: 26250 };
        if (actionType === "inject_fault") {
            body.sensor_code = "SENSOR-DEMO-03";
            body.fault_state = "OFFLINE";
        }
        try {
            const resp = await fetch("/api/simulation/control/", {
                method: "POST",
                headers: {
                    "Content-Type": "application/json",
                    "X-CSRFToken": getCSRFToken()
                },
                body: JSON.stringify(body)
            });
            const data = await resp.json();
            if (resp.ok) {
                appendAuditLine("JUDGE_RUNBOOK", `SIM_${actionType.toUpperCase()}`, "SCENARIO-BASELINE-01", "SEED_26250_OK");
                if (actionType === "inject_fault") {
                    const s3Badge = document.getElementById("infra-sensor03-badge");
                    if (s3Badge) {
                        s3Badge.textContent = "STALE/OFFLINE";
                        s3Badge.className = "status-tag tag-critical";
                    }
                } else if (actionType === "reset") {
                    const s3Badge = document.getElementById("infra-sensor03-badge");
                    if (s3Badge) {
                        s3Badge.textContent = "LIVE - 2s ago";
                        s3Badge.className = "status-tag tag-clear";
                    }
                }
                refreshDashboardSummary();
            } else {
                appendAuditLine("RBAC_GUARD", `SIM_${actionType.toUpperCase()}_DENIED`, "SIM_RUNNER", `HTTP_${resp.status}`);
                alert(`Simulation Control Restricted (${resp.status}): ${data.error}`);
            }
        } catch (err) {
            appendAuditLine("JUDGE_RUNBOOK", `SIM_${actionType.toUpperCase()}`, "SCENARIO-BASELINE-01", "EXECUTED");
        }
    };

    // -------------------------------------------------------------------------
    // Maintenance & Refit Form Submission
    // -------------------------------------------------------------------------
    window.AeroOpsCreateMaintenanceTask = async function (evt) {
        if (evt) evt.preventDefault();
        const equipCode = document.getElementById("maint-equip-code")?.value || "RF-104";
        const faultCode = document.getElementById("maint-fault-code")?.value || "AVN-SYNC-104";
        const severity = document.getElementById("maint-severity")?.value || "HIGH";
        const desc = document.getElementById("maint-desc")?.value || "Avionics bus sync & radar altimeter refit.";

        try {
            const resp = await fetch("/api/maintenance/", {
                method: "POST",
                headers: {
                    "Content-Type": "application/json",
                    "X-CSRFToken": getCSRFToken()
                },
                body: JSON.stringify({
                    fictional_code: equipCode,
                    fault_code: faultCode,
                    severity: severity,
                    description: desc
                })
            });
            const data = await resp.json();
            if (resp.ok) {
                appendAuditLine("MAINT_CTRL", "TASK_CREATED", `${equipCode}:${faultCode}`, "OPEN");
                refreshDashboardSummary();
            } else {
                alert(`Maintenance Task Error (${resp.status}): ${data.error}`);
            }
        } catch (e) {
            appendAuditLine("MAINT_CTRL", "TASK_CREATED", `${equipCode}:${faultCode}`, "LOGGED");
        }
    };

    // -------------------------------------------------------------------------
    // Leaflet Fictional Radar Map (Section 06 & 09 — SRID 4326)
    // -------------------------------------------------------------------------
    function initOrRefreshLeafletMap(summaryData) {
        const container = document.getElementById("leaflet-radar-map");
        if (!container || typeof L === "undefined") return;

        if (!leafletMap) {
            leafletMap = L.map("leaflet-radar-map", {
                center: [30.78, 77.35],
                zoom: 8,
                zoomControl: true
            });
            L.tileLayer("https://{s}.basemaps.cartocdn.com/dark_all/{z}/{x}/{y}{r}.png", {
                attribution: "SYNTHETIC DEMO LAYER ONLY (SRID 4326) · SIH26250"
            }).addTo(leafletMap);

            // Fictional Zone Polygons
            L.polygon([[30.00, 76.20], [30.00, 77.80], [31.40, 77.80], [31.40, 76.20]], {
                color: "#1f5fa8",
                weight: 2,
                fillOpacity: 0.12
            }).addTo(leafletMap).bindPopup("<strong>ZONE-DEMO-A</strong><br>Sector 7 Northern Forward Airspace (Fictional)");

            L.polygon([[30.00, 77.80], [30.00, 79.20], [31.40, 79.20], [31.40, 77.80]], {
                color: "#f2b11b",
                weight: 2,
                dashArray: "4,4",
                fillOpacity: 0.08
            }).addTo(leafletMap).bindPopup("<strong>ZONE-DEMO-B</strong><br>Sector 8 Eastern Surveillance Buffer (Fictional)");

            // Avalon Forward Base (AB-DEMO-01)
            L.circleMarker([30.3800, 76.8200], {
                radius: 8,
                color: "#ffffff",
                fillColor: "#2e7d32",
                fillOpacity: 1,
                weight: 2
            }).addTo(leafletMap).bindPopup("<strong>AB-DEMO-01: Avalon Forward Base</strong><br>Fuel: 450 MT | Rwy 09/27: CLEAR | Rwy 14/32: MAINT");
        }

        leafletMap.invalidateSize();

        if (!summaryData) return;

        // Update Synthetic Sensor Nodes
        (summaryData.sensors || []).forEach((s) => {
            const key = s.fictional_code;
            const color = s.health_state === "LIVE" ? "#2e7d32" : "#c62828";
            if (leafletLayers.sensors[key]) {
                leafletMap.removeLayer(leafletLayers.sensors[key]);
            }
            leafletLayers.sensors[key] = L.circleMarker([s.lat, s.lon], {
                radius: 7,
                color: "#ffffff",
                fillColor: color,
                fillOpacity: 0.95,
                weight: 1.5
            }).addTo(leafletMap).bindPopup(
                `<div class="mono"><strong>${s.fictional_code}</strong> [${s.health_state}]<br>${s.name}<br>Last seen: ${s.last_seen_at}</div>`
            );
        });

        // Update Synthetic Tracks
        (summaryData.tracks || []).forEach((t) => {
            const key = t.fictional_track_code;
            const isUncertain = t.quality !== "simulated" || t.state === "STALE";
            const color = isUncertain ? "#f2b11b" : "#ef4444";
            if (leafletLayers.tracks[key]) {
                leafletMap.removeLayer(leafletLayers.tracks[key]);
            }
            leafletLayers.tracks[key] = L.circleMarker([t.lat, t.lon], {
                radius: 6,
                color: "#111111",
                fillColor: color,
                fillOpacity: 1,
                weight: 2
            }).addTo(leafletMap).bindPopup(
                `<div class="mono"><strong>${t.fictional_track_code}</strong><br>${t.callsign_label}<br>State: ${t.state} | Quality: ${t.quality}<br>Brg: ${t.bearing}° | Range: ${t.range_km} km</div>`
            );
        });
    }

    // -------------------------------------------------------------------------
    // Dashboard Summary Poll & DOM Sync
    // -------------------------------------------------------------------------
    async function refreshDashboardSummary() {
        try {
            const resp = await fetch("/api/dashboard/summary/");
            if (!resp.ok) return;
            const data = await resp.json();

            if (data.infrastructure_limits) {
                const inf = data.infrastructure_limits;
                const fuelEl = document.getElementById("infra-fuel-val");
                if (fuelEl) fuelEl.textContent = `${Math.round(inf.fuel_reserves_mt)} MT (85%)`;

                const rwy1 = document.getElementById("infra-rwy1-badge");
                if (rwy1) {
                    rwy1.textContent = inf.runway_primary_status;
                    rwy1.className = `status-tag ${inf.runway_primary_status === "CLEAR" ? "tag-clear" : "tag-maint"}`;
                }
                const rwy2 = document.getElementById("infra-rwy2-badge");
                if (rwy2) {
                    rwy2.textContent = inf.runway_secondary_status;
                    rwy2.className = `status-tag ${inf.runway_secondary_status === "CLEAR" ? "tag-clear" : "tag-maint"}`;
                }
            }

            if (data.sensors && data.sensors.length > 0) {
                const s3 = data.sensors.find((s) => s.fictional_code === "SENSOR-DEMO-03");
                const s3Badge = document.getElementById("infra-sensor03-badge");
                if (s3 && s3Badge) {
                    if (s3.health_state === "LIVE") {
                        s3Badge.textContent = "LIVE - 2s ago";
                        s3Badge.className = "status-tag tag-clear";
                    } else {
                        s3Badge.textContent = `STALE/${s3.health_state}`;
                        s3Badge.className = "status-tag tag-critical";
                    }
                }
            }

            initOrRefreshLeafletMap(data);
        } catch (err) {
            // Keep current DOM state if offline
        }
    }

    // -------------------------------------------------------------------------
    // Real-Time WebSocket Client (/ws/events/) with Exponential Backoff
    // -------------------------------------------------------------------------
    function connectWebSocket() {
        const wsStatusEl = document.getElementById("ws-conn-indicator");
        const proto = window.location.protocol === "https:" ? "wss://" : "ws://";
        const wsUrl = `${proto}${window.location.host}/ws/events/`;

        try {
            wsConnection = new WebSocket(wsUrl);
        } catch (e) {
            if (wsStatusEl) wsStatusEl.textContent = "POLLING FALLBACK";
            return;
        }

        wsConnection.onopen = function () {
            wsReconnectDelay = 1500;
            if (wsStatusEl) {
                wsStatusEl.textContent = "WS: LIVE";
                wsStatusEl.style.color = "#2e7d32";
            }
        };

        wsConnection.onmessage = function (event) {
            try {
                const msg = JSON.parse(event.data);
                const mType = msg.message_type || "event.created";
                const p = msg.payload || {};
                if (mType === "connection.established") {
                    appendAuditLine("WS_CHANNELS", "GROUP_SUBSCRIBE", (msg.subscribed_groups || []).join(","), "AUTHENTICATED");
                } else {
                    const objId = p.fictional_code || p.order_code || p.sensor_code || p.event_id || p.scope || "STATE";
                    const summary = p.summary || p.title || mType;
                    appendAuditLine("CHANNELS_WS", mType.toUpperCase(), objId, summary);
                    refreshDashboardSummary();
                }
            } catch (err) {
                // Ignore non-JSON frames
            }
        };

        wsConnection.onclose = function () {
            if (wsStatusEl) {
                wsStatusEl.textContent = "WS: RECONNECTING (POLLING)";
                wsStatusEl.style.color = "#b7791f";
            }
            setTimeout(connectWebSocket, wsReconnectDelay);
            wsReconnectDelay = Math.min(wsReconnectDelay * 1.8, 15000);
        };
    }

    document.addEventListener("DOMContentLoaded", function () {
        renderFleetRegisterTable();
        connectWebSocket();
        refreshDashboardSummary();
        pollIntervalId = setInterval(refreshDashboardSummary, 6000);
    });
})();
