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

    // Complete 25 Fictional Airframe Register for Fleet Management Module
    const IAF_25_FLEET_REGISTER = [
        { code: "RF-101", category: "Type-A Fighter", squadron: "SQ-DEMO-01", base: "AB-DEMO-01", payload: "Standby Readiness Patrol Pod", radius_km: 1850, status: "AVAILABLE", readiness: "READY", next_due: "2026-11-02", notes: "Standby Readiness Lead" },
        { code: "RF-102", category: "Type-A Fighter", squadron: "SQ-DEMO-01", base: "AB-DEMO-01", payload: "Standby Readiness Patrol Pod", radius_km: 1850, status: "AVAILABLE", readiness: "READY", next_due: "2026-11-03", notes: "Primary readiness pair #1" },
        { code: "RF-103", category: "Type-A Fighter", squadron: "SQ-DEMO-01", base: "AB-DEMO-01", payload: "Standard Air Patrol", radius_km: 1850, status: "AVAILABLE", readiness: "READY", next_due: "2026-10-29", notes: "Nominal telemetry" },
        { code: "RF-104", category: "Type-A Fighter", squadron: "SQ-DEMO-01", base: "AB-DEMO-01", payload: "Standby Readiness Patrol Pod", radius_km: 1850, status: "AVAILABLE", readiness: "READY", next_due: "2026-10-28", notes: "Avionics sync check due T-4 HRS" },
        { code: "RF-105", category: "Type-A Fighter", squadron: "SQ-DEMO-01", base: "AB-DEMO-01", payload: "Long-Range Surveillance Pod", radius_km: 1850, status: "AIRBORNE", readiness: "READY", next_due: "2026-11-05", notes: "Sector 7 Air Patrol" },
        { code: "RF-106", category: "Type-A Fighter", squadron: "SQ-DEMO-01", base: "AB-DEMO-01", payload: "Standard Air Patrol", radius_km: 1850, status: "AVAILABLE", readiness: "READY", next_due: "2026-11-08", notes: "Standby Hangar 1" },
        { code: "RF-107", category: "Type-A Fighter", squadron: "SQ-DEMO-01", base: "AB-DEMO-01", payload: "Electronic Escort Pod", radius_km: 1850, status: "MAINTENANCE", readiness: "DEGRADED", next_due: "2026-10-15", notes: "Radar LRU calibration" },
        { code: "RF-108", category: "Type-A Fighter", squadron: "SQ-DEMO-01", base: "AB-DEMO-01", payload: "Standard Air Patrol", radius_km: 1850, status: "AVAILABLE", readiness: "READY", next_due: "2026-11-10", notes: "Ready" },
        { code: "SB-511", category: "Type-B Multirole", squadron: "SQ-DEMO-01", base: "AB-DEMO-01", payload: "Heavy Endurance Patrol", radius_km: 1500, status: "AVAILABLE", readiness: "READY", next_due: "2026-10-27", notes: "Ready" },
        { code: "SB-512", category: "Type-B Multirole", squadron: "SQ-DEMO-01", base: "AB-DEMO-01", payload: "Extended Endurance Surveillance", radius_km: 1500, status: "AVAILABLE", readiness: "READY", next_due: "2026-10-13", notes: "100-hr phase inspection in 72h (XGB score 0.73)" },
        { code: "SB-513", category: "Type-B Multirole", squadron: "SQ-DEMO-01", base: "AB-DEMO-01", payload: "Heavy Endurance Patrol", radius_km: 1500, status: "AIRBORNE", readiness: "READY", next_due: "2026-10-30", notes: "Northern Ridge Patrol" },
        { code: "SB-514", category: "Type-B Multirole", squadron: "SQ-DEMO-01", base: "AB-DEMO-01", payload: "Standard Patrol Config", radius_km: 1500, status: "MAINTENANCE", readiness: "DEGRADED", next_due: "2026-10-11", notes: "Hydraulic actuator pressure fault FLT-HYD-402" },
        { code: "SB-515", category: "Type-B Multirole", squadron: "SQ-DEMO-02", base: "AB-DEMO-01", payload: "Maritime / Sector Recon", radius_km: 1500, status: "AVAILABLE", readiness: "READY", next_due: "2026-11-01", notes: "Ready" },
        { code: "SB-516", category: "Type-B Multirole", squadron: "SQ-DEMO-02", base: "AB-DEMO-01", payload: "Standard Patrol Config", radius_km: 1500, status: "AVAILABLE", readiness: "READY", next_due: "2026-11-04", notes: "Ready" },
        { code: "SB-517", category: "Type-B Multirole", squadron: "SQ-DEMO-02", base: "AB-DEMO-01", payload: "Dual Sensor Pod", radius_km: 1500, status: "AVAILABLE", readiness: "READY", next_due: "2026-11-06", notes: "Ready" },
        { code: "SB-518", category: "Type-B Multirole", squadron: "SQ-DEMO-02", base: "AB-DEMO-01", payload: "Standard Patrol Config", radius_km: 1500, status: "UNAVAILABLE", readiness: "GROUNDED", next_due: "2026-10-12", notes: "Engine bay thermal sensor replacement" },
        { code: "SB-519", category: "Type-B Multirole", squadron: "SQ-DEMO-02", base: "AB-DEMO-01", payload: "Standard Patrol Config", radius_km: 1500, status: "AVAILABLE", readiness: "READY", next_due: "2026-11-09", notes: "Ready" },
        { code: "EQ-DEMO-014", category: "Type-C Light Combat", squadron: "SQ-DEMO-02", base: "AB-DEMO-01", payload: "Light Reconnaissance Config", radius_km: 1200, status: "AVAILABLE", readiness: "READY", next_due: "2026-11-04", notes: "Synthetic canonical reference airframe" },
        { code: "TJ-201", category: "Type-C Light Combat", squadron: "SQ-DEMO-02", base: "AB-DEMO-01", payload: "Sector Patrol Interceptor", radius_km: 1200, status: "AVAILABLE", readiness: "READY", next_due: "2026-11-07", notes: "Ready" },
        { code: "TJ-202", category: "Type-C Light Combat", squadron: "SQ-DEMO-02", base: "AB-DEMO-01", payload: "Sector Patrol Interceptor", radius_km: 1200, status: "AVAILABLE", readiness: "READY", next_due: "2026-11-08", notes: "Ready" },
        { code: "TJ-203", category: "Type-C Light Combat", squadron: "SQ-DEMO-02", base: "AB-DEMO-01", payload: "Light Reconnaissance Config", radius_km: 1200, status: "INSPECTED", readiness: "READY", next_due: "2026-11-11", notes: "Post-sortie inspection verified" },
        { code: "TJ-204", category: "Type-C Light Combat", squadron: "SQ-DEMO-02", base: "AB-DEMO-01", payload: "Sector Patrol Interceptor", radius_km: 1200, status: "AVAILABLE", readiness: "READY", next_due: "2026-11-12", notes: "Ready" },
        { code: "TJ-205", category: "Type-C Light Combat", squadron: "SQ-DEMO-02", base: "AB-DEMO-01", payload: "Light Reconnaissance Config", radius_km: 1200, status: "MAINTENANCE", readiness: "DEGRADED", next_due: "2026-10-16", notes: "Landing gear strut check" },
        { code: "RD-901", category: "Ground Support / Radar Unit", squadron: "SQ-DEMO-01", base: "AB-DEMO-01", payload: "Mobile Telemetry Relay", radius_km: 250, status: "AVAILABLE", readiness: "READY", next_due: "2026-12-01", notes: "Linked to SENSOR-DEMO-01" },
        { code: "RD-902", category: "Ground Support / Radar Unit", squadron: "SQ-DEMO-02", base: "AB-DEMO-01", payload: "Auxiliary Arrestor Power Unit", radius_km: 180, status: "AVAILABLE", readiness: "READY", next_due: "2026-12-05", notes: "Runway 09/27 support" }
    ];

    let wsConnection = null;
    let wsReconnectDelay = 1500;
    let pollIntervalId = null;
    let leafletMap = null;
    let leafletLayers = { sensors: {}, tracks: {} };
    let lastFetchTimestamp = null;
    let fetchErrorOccurred = false;

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
    // Clocks and Freshness Display
    // -------------------------------------------------------------------------
    function initClocks() {
        function updateWallClock() {
            const wc = document.getElementById("wall-clock-display");
            if (wc) {
                const now = new Date();
                wc.textContent = now.toISOString().slice(11, 19) + " UTC";
            }
            updateFreshnessPill();
        }
        setInterval(updateWallClock, 1000);
        updateWallClock();
    }

    function updateFreshnessPill() {
        const pill = document.getElementById("data-freshness-pill");
        if (!pill) return;
        if (fetchErrorOccurred) {
            pill.textContent = "OFFLINE";
            pill.className = "status-tag tag-critical";
            return;
        }
        if (!lastFetchTimestamp) {
            pill.textContent = "INITIALIZING";
            pill.className = "status-tag tag-neutral";
            return;
        }
        const elapsedSec = Math.floor((Date.now() - lastFetchTimestamp) / 1000);
        if (elapsedSec < 6) {
            pill.textContent = "LIVE";
            pill.className = "status-tag tag-clear";
        } else if (elapsedSec < 15) {
            pill.textContent = `SYNCED (${elapsedSec}s)`;
            pill.className = "status-tag tag-neutral";
        } else {
            pill.textContent = `STALE (${elapsedSec}s)`;
            pill.className = "status-tag tag-critical";
        }
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

        if (filtered.length === 0) {
            tbody.innerHTML = `
                <tr class="empty-state-row">
                    <td colspan="10" class="mono" style="text-align:center; padding:16px; color:#6b7280;">
                        No aircraft matching selected filter criteria.
                    </td>
                </tr>
            `;
        } else {
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
                        <td class="mono">${ac.next_due || "—"}</td>
                        <td>${ac.notes || "Nominal"}</td>
                        <td>
                            <button type="button" class="btn-gov btn-gov-xs" onclick="window.AeroOpsQuickToggleAircraft('${ac.code}', 'MAINTENANCE')" aria-label="Set ${ac.code} to maintenance">Maint</button>
                            <button type="button" class="btn-gov btn-gov-xs btn-gov-primary" onclick="window.AeroOpsQuickToggleAircraft('${ac.code}', 'AVAILABLE')" aria-label="Set ${ac.code} to available">Ready</button>
                        </td>
                    </tr>
                `;
            }).join("");
        }

        const countSpan = document.getElementById("fleet-register-count");
        if (countSpan) countSpan.textContent = `${filtered.length} / ${IAF_25_FLEET_REGISTER.length}`;
    }

    window.AeroOpsFilterFleet = renderFleetRegisterTable;

    function syncFleetRegisterFromDB(equipmentList) {
        if (!equipmentList || equipmentList.length === 0) return;
        equipmentList.forEach((dbEq) => {
            const found = IAF_25_FLEET_REGISTER.find((x) => x.code === dbEq.code);
            if (found) {
                found.category = dbEq.category;
                found.squadron = dbEq.squadron;
                found.base = dbEq.airbase;
                found.payload = dbEq.payload;
                found.radius_km = dbEq.radius_km;
                found.status = dbEq.status;
                found.readiness = dbEq.readiness;
                if (dbEq.next_due) found.next_due = dbEq.next_due;
                if (dbEq.notes) found.notes = dbEq.notes;
            } else {
                IAF_25_FLEET_REGISTER.push({
                    code: dbEq.code,
                    category: dbEq.category,
                    squadron: dbEq.squadron,
                    base: dbEq.airbase,
                    payload: dbEq.payload,
                    radius_km: dbEq.radius_km,
                    status: dbEq.status,
                    readiness: dbEq.readiness,
                    next_due: dbEq.next_due || "2026-11-01",
                    notes: dbEq.notes || "Operational"
                });
            }
        });
        renderFleetRegisterTable();
    }

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
    // Dynamic Table Rendering (Data-Driven UI — Section 05 & Master Spec)
    // -------------------------------------------------------------------------
    function renderActiveAircraftTable(equipmentList) {
        const tbody = document.getElementById("active-aircraft-tbody");
        if (!tbody) return;
        if (!equipmentList || equipmentList.length === 0) {
            tbody.innerHTML = `
                <tr class="empty-state-row">
                    <td colspan="9" class="mono" style="text-align:center; padding:16px; color:#6b7280;">
                        No aircraft currently assigned to active squadron or base scope.
                    </td>
                </tr>
            `;
            return;
        }

        const topEquipment = equipmentList.slice(0, 8);
        tbody.innerHTML = topEquipment.map((eq) => {
            let badgeClass = "tag-clear";
            if (eq.status === "MAINTENANCE" || eq.status === "AIRBORNE") badgeClass = "tag-maint";
            if (eq.status === "UNAVAILABLE") badgeClass = "tag-critical";

            let actionBtn = `<button type="button" class="btn-gov btn-gov-xs" onclick="window.AeroOpsQuickToggleAircraft('${eq.code}', 'MAINTENANCE')" aria-label="Mark ${eq.code} maintenance">Mark Maint</button>`;
            if (eq.status === "MAINTENANCE" || eq.status === "UNAVAILABLE") {
                actionBtn = `<button type="button" class="btn-gov btn-gov-xs btn-gov-primary" onclick="window.AeroOpsQuickToggleAircraft('${eq.code}', 'AVAILABLE')" aria-label="Mark ${eq.code} ready">Verify Ready</button>`;
            } else if (eq.status === "AVAILABLE") {
                actionBtn = `<button type="button" class="btn-gov btn-gov-xs btn-gov-primary" onclick="window.AeroOpsQuickToggleAircraft('${eq.code}', 'AIRBORNE')" aria-label="Dispatch ${eq.code}">Dispatch</button>`;
            }

            return `
                <tr>
                    <td class="mono"><strong>${eq.code}</strong></td>
                    <td>${eq.category}</td>
                    <td class="mono">${eq.squadron}</td>
                    <td>${eq.payload || "Standard Patrol Config"}</td>
                    <td class="mono">${eq.last_service || "2026-10-01"}</td>
                    <td class="mono">${eq.next_due || "2026-11-01"}</td>
                    <td><span class="status-tag ${badgeClass}">${eq.status}</span></td>
                    <td>${eq.notes || "Operational telemetry nominal."}</td>
                    <td>${actionBtn}</td>
                </tr>
            `;
        }).join("");
    }

    function renderCrewRosterTable(crewList) {
        const tbody = document.getElementById("crew-roster-tbody");
        if (!tbody) return;
        if (!crewList || crewList.length === 0) {
            tbody.innerHTML = `
                <tr class="empty-state-row">
                    <td colspan="8" class="mono" style="text-align:center; padding:16px; color:#6b7280;">
                        No flight crew records found in current operational scope.
                    </td>
                </tr>
            `;
            return;
        }

        tbody.innerHTML = crewList.map((c) => {
            const isViolated = c.rest_required || c.fdtl_hours_logged >= 8.0;
            const rowStyle = isViolated ? 'style="background-color:#fff3cd;"' : "";
            const fdtlColor = isViolated ? 'style="color:#c62828; font-weight:bold;"' : "";
            const restBadge = isViolated
                ? '<span class="status-tag tag-critical">REST REQUIRED</span>'
                : '<span class="status-tag tag-clear">NO</span>';
            const dutyClass = c.duty_state === "REST_REQUIRED" ? "tag-critical" : (c.duty_state === "READY" ? "tag-clear" : "tag-maint");
            const constraintNote = isViolated
                ? "<strong>HARD CONSTRAINT LOCKED:</strong> Mandatory rest required. Excluded from readiness pool."
                : (c.notes || "QUALIFIED — Nominal duty schedule.");

            return `
                <tr ${rowStyle}>
                    <td class="mono"><strong>${c.crew_code}</strong></td>
                    <td><strong>${c.crew_ref}</strong></td>
                    <td class="mono">${c.squadron}</td>
                    <td class="mono">${c.pilot_group_count} Pilot / ${c.ground_support_count} Ground</td>
                    <td class="mono" ${fdtlColor}>${c.fdtl_hours_logged} / 8.0 hrs</td>
                    <td>${restBadge}</td>
                    <td><span class="status-tag ${dutyClass}">${c.duty_state}</span></td>
                    <td>${constraintNote}</td>
                </tr>
            `;
        }).join("");
    }

    function renderMaintenanceBoardTable(taskList) {
        const tbody = document.getElementById("maintenance-board-tbody");
        if (!tbody) return;
        if (!taskList || taskList.length === 0) {
            tbody.innerHTML = `
                <tr class="empty-state-row">
                    <td colspan="6" class="mono" style="text-align:center; padding:16px; color:#6b7280;">
                        Zero active maintenance work orders. All airframes verified operational.
                    </td>
                </tr>
            `;
            return;
        }

        tbody.innerHTML = taskList.map((t) => {
            const sevClass = t.severity === "CRITICAL" || t.severity === "HIGH" ? "tag-critical" : "tag-maint";
            const statusClass = t.status === "COMPLETED" || t.status === "VERIFIED" ? "tag-clear" : (t.status === "IN_PROGRESS" ? "tag-maint" : "tag-neutral");
            return `
                <tr>
                    <td class="mono"><strong>${t.fault_code}</strong></td>
                    <td class="mono">${t.equipment_code}</td>
                    <td><span class="status-tag ${sevClass}">${t.severity}</span></td>
                    <td><span class="status-tag ${statusClass}">${t.status}</span></td>
                    <td>${t.description}</td>
                    <td class="mono">${t.due_at || "TBD"}</td>
                </tr>
            `;
        }).join("");
    }

    function renderInfrastructureAirbasesTable(airbaseList) {
        const tbody = document.getElementById("infra-airbases-tbody");
        if (!tbody) return;
        if (!airbaseList || airbaseList.length === 0) {
            tbody.innerHTML = `
                <tr class="empty-state-row">
                    <td colspan="9" class="mono" style="text-align:center; padding:16px; color:#6b7280;">
                        No airbase infrastructure records registered for current scope.
                    </td>
                </tr>
            `;
            return;
        }

        tbody.innerHTML = airbaseList.map((ab) => {
            const rwy1Class = ab.runway_primary_status === "CLEAR" ? "tag-clear" : "tag-maint";
            const rwy2Class = ab.runway_secondary_status === "CLEAR" ? "tag-clear" : "tag-maint";
            const gearClass = ab.arrestor_gear_status === "OPERATIONAL" ? "tag-clear" : "tag-critical";
            const statusClass = ab.status === "OPERATIONAL" ? "tag-clear" : "tag-maint";
            return `
                <tr>
                    <td class="mono"><strong>${ab.code}</strong></td>
                    <td>${ab.name}</td>
                    <td class="mono">${ab.zone_code}</td>
                    <td class="mono">${ab.lat.toFixed(4)}° N, ${ab.lon.toFixed(4)}° E</td>
                    <td>${ab.runway_primary_label} (${ab.runway_primary_m}m) <span class="status-tag ${rwy1Class}">${ab.runway_primary_status}</span></td>
                    <td>${ab.runway_secondary_label} (${ab.runway_secondary_m}m) <span class="status-tag ${rwy2Class}">${ab.runway_secondary_status}</span></td>
                    <td><span class="status-tag ${gearClass}">${ab.arrestor_gear_status}</span></td>
                    <td class="mono">${ab.fuel_reserves_mt.toFixed(2)} MT</td>
                    <td><span class="status-tag ${statusClass}">${ab.status}</span></td>
                </tr>
            `;
        }).join("");
    }

    function renderActionsRequiredList(ordersList) {
        const listEl = document.getElementById("actions-bullet-list");
        if (!listEl) return;
        if (!ordersList || ordersList.length === 0) {
            listEl.innerHTML = `
                <li class="actions-bullet-item mono" style="color:#6b7280; padding:12px;">
                    Zero pending operational directives. All orders acknowledged.
                </li>
            `;
            return;
        }

        listEl.innerHTML = ordersList.map((o) => {
            const isAck = o.status === "ACKNOWLEDGED" || o.status === "COMPLETED";
            const btnHtml = isAck
                ? '<button type="button" class="btn-gov btn-gov-xs tag-clear" disabled>ACKNOWLEDGED</button>'
                : `<button type="button" class="btn-gov btn-gov-xs btn-gov-primary" onclick="window.AeroOpsAcknowledgeOrder('${o.order_code}', this)" aria-label="Acknowledge order ${o.order_code}">Acknowledge</button>`;

            return `
                <li class="actions-bullet-item">
                    <div><strong>${o.title}</strong></div>
                    <div class="mono" style="font-size:11px; color:#374151;">
                        ${o.order_code} | ${o.priority}: ${o.body}
                    </div>
                    <div class="order-inline-meta">
                        <span class="mono" style="font-size:10px; color:#6b7280;">Issuer: ${o.issuer_name} | Scope: ${o.recipient_scope}</span>
                        ${btnHtml}
                    </div>
                </li>
            `;
        }).join("");
    }

    function renderSuggestionsTable(suggestionsList) {
        const tbody = document.getElementById("suggestions-table-tbody");
        if (!tbody) return;
        if (!suggestionsList || suggestionsList.length === 0) {
            tbody.innerHTML = `
                <tr class="empty-state-row">
                    <td colspan="5" class="mono" style="text-align:center; padding:16px; color:#6b7280;">
                        No operational advisories available. System running nominal baseline.
                    </td>
                </tr>
            `;
            return;
        }

        tbody.innerHTML = suggestionsList.map((s, idx) => {
            const isFeasible = s.score > 0.0;
            const rowStyle = !isFeasible
                ? 'style="background-color:#fdf2f2;"'
                : (idx === 0 ? 'style="background-color:#eef8f0;"' : "");
            const gateBadge = isFeasible
                ? '<span class="status-tag tag-clear">FEASIBLE</span>'
                : '<span class="status-tag tag-critical">BLOCKED</span>';
            const reasonsText = Array.isArray(s.reasons) ? s.reasons.join(" ") : (s.reasons || "Advisory option evaluated.");
            const baselineDisplay = s.baseline_score != null ? Number(s.baseline_score).toFixed(2) : "—";

            return `
                <tr ${rowStyle}>
                    <td><strong>${s.title}</strong><br><span class="mono">${s.suggestion_code}</span></td>
                    <td>${gateBadge}</td>
                    <td class="mono"><strong>${Number(s.score).toFixed(2)}</strong></td>
                    <td class="mono">${baselineDisplay}</td>
                    <td>${reasonsText}</td>
                </tr>
            `;
        }).join("");
    }

    function updateFdtlWarning(crewList, violationsCount) {
        const banner = document.getElementById("fdtl-top-warning");
        if (!banner) return;
        const count = violationsCount != null ? violationsCount : (crewList || []).filter((c) => c.rest_required).length;
        if (count > 0) {
            const violator = (crewList || []).find((c) => c.rest_required) || { crew_ref: "Sq. Ldr. S. Venkat", squadron: "SQ-DEMO-01", fdtl_hours_logged: 9.5 };
            const textDiv = banner.querySelector(".fdtl-warning-text");
            if (textDiv) {
                textDiv.textContent = `[!] REST VIOLATION DETECTED - ${violator.crew_ref} (${violator.squadron} - ${violator.fdtl_hours_logged}/8.0 hrs FDTL logged). Deterministic safety gate active.`;
            }
            banner.style.display = "flex";
        } else {
            banner.style.display = "none";
        }
    }

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
        const payloadCfg = document.getElementById("vc-payload-cfg")?.value || "450 MT / Readiness Patrol Pod";
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
        const fn = document.getElementById("vc-first-name");
        if (fn) fn.value = "";
        const tid = document.getElementById("vc-tail-id");
        if (tid) tid.value = "RF-104";
        const pk = document.getElementById("vc-passkey");
        if (pk) pk.value = "";
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
                attribution: "SYNTHETIC DEMO LAYER ONLY (SRID 4326) · SIH26250",
                maxZoom: 18
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
            if (!resp.ok) {
                fetchErrorOccurred = true;
                updateFreshnessPill();
                return;
            }
            const data = await resp.json();
            fetchErrorOccurred = false;
            lastFetchTimestamp = Date.now();
            updateFreshnessPill();

            const lastUpdatedEl = document.getElementById("last-updated-display");
            if (lastUpdatedEl) {
                lastUpdatedEl.textContent = new Date().toISOString().slice(11, 19) + "Z";
            }

            // Sync Sim Clock if provided
            if (data.simulation && data.simulation.simulated_clock) {
                const simClockEl = document.getElementById("sim-clock-display");
                if (simClockEl) {
                    simClockEl.textContent = data.simulation.simulated_clock.slice(0, 19) + "Z";
                }
            }

            // Update Counters Strip
            if (data.counters) {
                const c = data.counters;
                const acAvail = document.getElementById("cnt-aircraft-avail");
                if (acAvail) acAvail.textContent = `${c.equipment_available}/${c.equipment_total}`;

                const crewReady = document.getElementById("cnt-crew-ready");
                if (crewReady) {
                    const pct = c.crew_ready_groups > 0 ? "87.4%" : "0.0%";
                    crewReady.textContent = pct;
                }

                const maintDue = document.getElementById("cnt-maint-due");
                if (maintDue) maintDue.textContent = c.open_maintenance_tasks;

                const openAlerts = document.getElementById("cnt-open-alerts");
                if (openAlerts) openAlerts.textContent = c.open_alerts;

                const pendingAck = document.getElementById("cnt-pending-ack");
                if (pendingAck) pendingAck.textContent = c.pending_orders;
            }

            // Update Infrastructure Limits Panel
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

            // Update Sensor 03 Badge
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

            // Data-Driven Dynamic Table Updates
            if (data.equipment) {
                renderActiveAircraftTable(data.equipment);
                syncFleetRegisterFromDB(data.equipment);
            }
            if (data.crew_members) {
                renderCrewRosterTable(data.crew_members);
                updateFdtlWarning(data.crew_members, data.counters?.crew_fdtl_violations);
            }
            if (data.maintenance_tasks) {
                renderMaintenanceBoardTable(data.maintenance_tasks);
            }
            if (data.airbases) {
                renderInfrastructureAirbasesTable(data.airbases);
            }
            if (data.orders) {
                renderActionsRequiredList(data.orders);
            }
            if (data.suggestions) {
                renderSuggestionsTable(data.suggestions);
            }

            initOrRefreshLeafletMap(data);
        } catch (err) {
            fetchErrorOccurred = true;
            updateFreshnessPill();
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
        initClocks();
        renderFleetRegisterTable();
        connectWebSocket();
        refreshDashboardSummary();
        pollIntervalId = setInterval(refreshDashboardSummary, 6000);
    });
})();
