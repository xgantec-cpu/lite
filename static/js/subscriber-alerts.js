(() => {
  const page = document.querySelector("[data-subscriber-alerts]");
  if (!page) return;

  const publicKey = page.dataset.publicKey || "";
  const subscribeUrl = page.dataset.subscribeUrl;
  const preferencesUrl = page.dataset.preferencesUrl;
  const removeAreaUrl = page.dataset.removeAreaUrl;
  const travelUrl = page.dataset.travelUrl;
  const travelLocationUrl = page.dataset.travelLocationUrl;
  const travelStopUrl = page.dataset.travelStopUrl;
  const csrfToken = document.querySelector("input[name=csrfmiddlewaretoken]")?.value || "";
  const status = page.querySelector("[data-subscriber-status]");
  const areaOptions = [...page.querySelectorAll("[data-alert-area-option]")];
  const areaSearch = page.querySelector("[data-area-search]");
  const areaEmpty = page.querySelector("[data-area-empty]");
  const activeAreas = page.querySelector("[data-active-areas]");
  const saveAreasButton = page.querySelector("[data-save-areas]");
  const travelForm = page.querySelector("[data-travel-form]");
  const originSelect = travelForm?.querySelector("[name='origin_area']");
  const destinationSelect = travelForm?.querySelector("[name='destination_area']");
  const travelResult = page.querySelector("[data-travel-route]");
  const stopTravelButton = page.querySelector("[data-stop-travel]");
  const gpsButton = page.querySelector("[data-use-gps]");
  const gpsIndicator = page.querySelector("[data-gps-indicator]");
  const gpsStatus = page.querySelector("[data-gps-status]");
  const livePosition = page.querySelector("[data-live-position]");
  const routeMapElement = page.querySelector("[data-travel-route-map]");
  const routeMapShell = page.querySelector("[data-travel-map-shell]");
  const fullscreenButton = page.querySelector("[data-map-fullscreen]");
  const routeMapState = page.querySelector("[data-map-route-state]");
  const routeMapLabels = page.querySelector("[data-map-route-labels]");
  const routeMapFrom = page.querySelector("[data-map-route-from]");
  const routeMapTo = page.querySelector("[data-map-route-to]");
  const routeMetrics = page.querySelector("[data-map-route-metrics]");
  const routeDistance = page.querySelector("[data-map-route-distance]");
  const routeDistanceLabel = page.querySelector("[data-map-route-distance-label]");
  const routeTime = page.querySelector("[data-map-route-time]");
  const routeStops = page.querySelector("[data-map-route-stops]");
  const routeTraffic = page.querySelector("[data-map-route-traffic]");
  const routeTrafficValue = page.querySelector("[data-map-route-traffic-value]");
  let registration;
  let subscription;
  let serviceWorkerPromise;
  let serviceWorkerError = "";
  let savedAreaIds = [];
  let gpsWatchId = null;
  let gpsActive = false;
  let travelMap;
  let travelMapLayer;
  let travelMapDepth;
  let travelMapLine;
  let travelMapUnderlay;
  let travelMapMarkers = [];
  let userLocationMarker;
  let userAccuracyCircle;
  let userLocationTrailLine;
  const userLocationTrail = [];
  let routeRenderToken = 0;
  let routeRequestController;
  let currentGpsPosition;
  let locationLookupPending = false;
  let originAreaResolved = false;

  const setStatus = (message, state = "") => {
    status.textContent = message;
    status.dataset.state = state;
  };

  const readablePushError = (error, fallback) => {
    const message = error?.message || "";
    if (/push service/i.test(message)) {
      const safari = /Safari/i.test(navigator.userAgent) && !/Chrome|CriOS|Edg/i.test(navigator.userAgent);
      return safari
        ? "Safari Web Push requires HTTPS and, on iPhone or iPad, adding this site to the Home Screen."
        : "This browser's push service rejected the subscription. Confirm HTTPS and the matching VAPID keys, then reload.";
    }
    return message || fallback;
  };

  const showCriticalAlert = (payload = {}) => {
    document.querySelector("[data-critical-alert]")?.remove();
    const overlay = document.createElement("section");
    overlay.className = "critical-alert-overlay";
    overlay.dataset.criticalAlert = "";
    overlay.setAttribute("role", "alertdialog");
    overlay.setAttribute("aria-live", "assertive");
    const label = document.createElement("strong");
    label.className = "critical-alert-label";
    label.textContent = "CRITICAL PUBLIC SAFETY ALERT";
    const title = document.createElement("h2");
    title.textContent = payload.title || "Urgent safety information";
    const body = document.createElement("p");
    body.textContent = payload.body || "Please follow the response team's instructions.";
    const area = document.createElement("span");
    area.className = "critical-alert-area";
    area.textContent = payload.area ? `District: ${payload.area}` : "District safety notice";
    const close = document.createElement("button");
    close.type = "button";
    close.className = "critical-alert-close";
    close.setAttribute("aria-label", "Close alert");
    close.textContent = "×";
    close.addEventListener("click", () => overlay.remove());
    const open = document.createElement("button");
    open.type = "button";
    open.className = "critical-alert-open";
    open.textContent = "Open safety notice";
    open.addEventListener("click", () => { window.location.href = payload.url || "/"; });
    const header = document.createElement("div");
    header.className = "critical-alert-header";
    header.append(label, close);
    overlay.append(header, title, body, area, open);
    document.body.appendChild(overlay);
    const expiresAt = Date.parse(payload.expires_at || "");
    if (Number.isFinite(expiresAt)) {
      const remaining = expiresAt - Date.now();
      if (remaining <= 0) overlay.remove();
      else window.setTimeout(() => overlay.remove(), remaining);
    }
  };

  const decodeKey = (value) => {
    const normalized = value.trim().replace(/^['"]|['"]$/g, "").replace(/\s/g, "").replace(/\+/g, "-").replace(/\//g, "_").replace(/=+$/, "");
    const padding = "=".repeat((4 - (normalized.length % 4)) % 4);
    const raw = window.atob((normalized + padding).replace(/-/g, "+").replace(/_/g, "/"));
    if (raw.length !== 65 || raw.charCodeAt(0) !== 4) {
      throw new Error("The Web Push public key is invalid. Check WEBPUSH_VAPID_PUBLIC_KEY.");
    }
    return Uint8Array.from(raw, (character) => character.charCodeAt(0));
  };

  const areaId = (option) => Number(option.dataset.areaId || option.value);
  const areaName = (option) => option.dataset.areaName || option.querySelector("strong")?.textContent || option.value;
  const isAreaSelected = (option) => option.getAttribute("aria-pressed") === "true" || option.checked === true;
  const setAreaSelected = (option, selected) => {
    if ("checked" in option) option.checked = selected;
    option.setAttribute("aria-pressed", String(selected));
    option.classList.toggle("is-selected", selected);
    const marker = option.querySelector("b[aria-hidden='true']");
    if (marker) marker.textContent = selected ? "✓" : "+";
  };

  const postJson = async (url, payload) => {
    const response = await fetch(url, {
      method: "POST",
      credentials: "same-origin",
      headers: {"Content-Type": "application/json", "X-CSRFToken": csrfToken},
      body: JSON.stringify(payload),
    });
    const data = await response.json().catch(() => ({}));
    if (!response.ok) throw new Error(data.error || "The request could not be saved.");
    return data;
  };

  const browserPayload = () => {
    const data = subscription?.toJSON();
    return {
      endpoint: data?.endpoint || "",
      keys: data?.keys || {},
      client_uuid: document.cookie.match(/(?:^|; )client_uuid=([^;]+)/)?.[1] || "",
    };
  };

  const ensureSubscription = async () => {
    if (serviceWorkerPromise) await serviceWorkerPromise;
    if (serviceWorkerError) throw new Error(serviceWorkerError);
    if (!("serviceWorker" in navigator) || !("PushManager" in window) || !("Notification" in window)) {
      throw new Error("This browser cannot receive safety alerts.");
    }
    if (!publicKey) throw new Error("Browser alerts are not configured on this server yet.");
    if (!registration) registration = await navigator.serviceWorker.ready;
    const permission = await Notification.requestPermission();
    if (permission !== "granted") throw new Error("Browser notification permission was not granted.");
    subscription = await registration.pushManager.getSubscription();
    if (!subscription) {
      const applicationServerKey = decodeKey(publicKey);
      subscription = await registration.pushManager.subscribe({
        userVisibleOnly: true,
        applicationServerKey,
      });
    }
    return browserPayload();
  };

  const optionalTravelSubscription = async () => {
    if (!subscription && serviceWorkerPromise) {
      await Promise.race([
        serviceWorkerPromise,
        new Promise((resolve) => window.setTimeout(resolve, 800)),
      ]);
    }
    if (!subscription && registration) {
      try {
        subscription = await registration.pushManager.getSubscription();
      } catch (error) {
        console.warn("The existing browser alert subscription could not be read.", error);
      }
    }
    if (subscription) {
      return {browser: browserPayload(), notice: ""};
    }
    return {
      browser: {},
      notice: "Route calculated without browser alerts. Subscribe to alerts above to receive safety notices along the corridor.",
    };
  };

  const renderActiveAreas = (areaIds) => {
    if (!activeAreas) return;
    const selected = areaOptions.filter((option) => areaIds.includes(areaId(option)));
    activeAreas.replaceChildren();
    const heading = document.createElement("strong");
    heading.textContent = "Selected districts";
    activeAreas.appendChild(heading);
    if (!selected.length) {
      const empty = document.createElement("span");
      empty.className = "subscriber-active-empty";
      empty.textContent = "No districts selected yet.";
      activeAreas.appendChild(empty);
      return;
    }
    selected.forEach((option) => {
      const chip = document.createElement("span");
      chip.className = "subscriber-selected-chip";
      const label = document.createElement("span");
      label.className = "subscriber-selected-chip-label";
      label.textContent = areaName(option);
      const removeButton = document.createElement("button");
      removeButton.type = "button";
      removeButton.className = "subscriber-selected-remove";
      removeButton.setAttribute("aria-label", `Remove ${areaName(option)} from saved districts`);
      removeButton.textContent = "×";
      removeButton.addEventListener("click", async () => {
        const selectedIds = areaOptions.filter(isAreaSelected).map(areaId).filter((id) => id !== areaId(option));
        setAreaSelected(option, false);
        renderActiveAreas(selectedIds);
        if (!savedAreaIds.includes(areaId(option)) || !subscription || !removeAreaUrl) return;
        removeButton.disabled = true;
        try {
          const result = await postJson(removeAreaUrl, {...browserPayload(), area_id: areaId(option)});
          savedAreaIds = result.areas.map(Number);
          setStatus(`${areaName(option)} was removed from your saved districts.`, "success");
        } catch (error) {
          setAreaSelected(option, true);
          renderActiveAreas(areaOptions.filter(isAreaSelected).map(areaId));
          setStatus(error.message || "The district could not be removed.", "error");
        }
      });
      chip.append(label, removeButton);
      activeAreas.appendChild(chip);
    });
  };

  const loadPreferences = async () => {
    if (!registration) registration = await navigator.serviceWorker.ready;
    subscription = await registration.pushManager.getSubscription();
    if (!subscription) {
      savedAreaIds = [];
      areaOptions.forEach((option) => setAreaSelected(option, false));
      renderActiveAreas([]);
      return;
    }
    const result = await postJson(preferencesUrl, {endpoint: subscription.endpoint});
    savedAreaIds = result.areas.map(Number);
    areaOptions.forEach((option) => setAreaSelected(option, result.areas.includes(areaId(option))));
    renderActiveAreas(result.areas);
    setStatus("Your saved notification places are ready.", "success");
  };

  const refreshAreaOptions = () => {
    const query = (areaSearch?.value || "").trim().toLocaleLowerCase();
    let visible = 0;
    areaOptions.forEach((option) => {
      const matches = !query || areaName(option).toLocaleLowerCase().includes(query)
        || (option.querySelector("small")?.textContent || "").toLocaleLowerCase().includes(query);
      option.hidden = !matches;
      if (matches) visible += 1;
    });
    if (areaEmpty) areaEmpty.hidden = visible > 0;
  };

  const resolveOriginArea = async (latitude, longitude) => {
    if (!travelLocationUrl || originAreaResolved || locationLookupPending) return;
    locationLookupPending = true;
    setStatus("Finding the starting district from your GPS position…");
    try {
      const result = await postJson(travelLocationUrl, {latitude, longitude});
      if (!result.area || !originSelect) throw new Error("The starting district could not be identified.");
      originSelect.value = String(result.area.id);
      originAreaResolved = true;
      setStatus(`${result.message} Route distance will be calculated after you choose the destination.`, "success");
      destinationSelect?.focus();
    } catch (error) {
      setStatus(error.message || "The starting district could not be identified. Choose it manually.", "error");
    } finally {
      locationLookupPending = false;
    }
  };

  const updateGpsUi = (message, state = "") => {
    if (gpsStatus) gpsStatus.textContent = message;
    if (gpsIndicator) {
      gpsIndicator.textContent = state === "live" ? "GPS live" : state === "error" ? "GPS unavailable" : "GPS standby";
    }
    if (gpsButton) {
      gpsButton.textContent = state === "live" ? "Stop live GPS view" : "Use GPS for live trip view";
      gpsButton.dataset.state = state;
    }
  };

  const stopGps = () => {
    if (gpsWatchId !== null && navigator.geolocation) navigator.geolocation.clearWatch(gpsWatchId);
    gpsWatchId = null;
    gpsActive = false;
    if (livePosition) livePosition.hidden = true;
    updateGpsUi("Location stays on this device.");
  };

  const startGps = () => {
    if (!navigator.geolocation) {
      updateGpsUi("This browser does not provide location services.", "error");
      setStatus("Live GPS is not available in this browser.", "error");
      return;
    }
    const localHost = ["localhost", "127.0.0.1", "[::1]"].includes(window.location.hostname);
    if (!window.isSecureContext && !localHost) {
      updateGpsUi("GPS requires a secure connection.", "error");
      setStatus("Live GPS requires HTTPS. Open the secure site, then try again.", "error");
      return;
    }
    if (gpsActive) {
      stopGps();
      setStatus("Live GPS view stopped. No location was sent to the server.", "success");
      return;
    }
    gpsActive = true;
    originAreaResolved = false;
    locationLookupPending = false;
    updateGpsUi("Requesting location permission…");
    setStatus("Requesting GPS permission for this device…");
    const handlePosition = (position) => {
      const {latitude, longitude, accuracy} = position.coords;
      currentGpsPosition = [latitude, longitude];
      const updated = new Date(position.timestamp || Date.now()).toLocaleTimeString([], {hour: "2-digit", minute: "2-digit"});
      if (livePosition) {
        livePosition.hidden = false;
        livePosition.textContent = `Live position ${latitude.toFixed(5)}, ${longitude.toFixed(5)} · accuracy ±${Math.round(accuracy)} m · updated ${updated}`;
      }
      updatePreciseLocation(latitude, longitude, accuracy);
      resolveOriginArea(latitude, longitude);
      updateGpsUi(`Live position updated at ${updated}. Exact coordinates stay on this device.`, "live");
      setStatus("GPS is live for this trip view. Your exact location is not stored by this page.", "success");
    };
    const handleError = (error) => {
      gpsActive = false;
      gpsWatchId = null;
      const message = error.code === 1 ? "Location permission was denied. You can enable it in browser settings." : "The device could not provide a current location.";
      updateGpsUi(message, "error");
      setStatus(message, "error");
    };
    const options = {enableHighAccuracy: true, maximumAge: 10000, timeout: 15000};
    gpsWatchId = navigator.geolocation.watchPosition(handlePosition, handleError, options);
    navigator.geolocation.getCurrentPosition(handlePosition, handleError, options);
  };

  const setMapState = (message) => {
    if (routeMapState) routeMapState.textContent = message;
  };

  const formatDistance = (meters) => {
    if (!Number.isFinite(meters)) return "—";
    return meters >= 1000 ? `${(meters / 1000).toFixed(meters >= 10000 ? 0 : 1)} km` : `${Math.round(meters)} m`;
  };

  const formatDuration = (seconds) => {
    if (!Number.isFinite(seconds)) return "—";
    const minutes = Math.max(1, Math.round(seconds / 60));
    if (minutes < 60) return `${minutes} min`;
    const hours = Math.floor(minutes / 60);
    const remainder = minutes % 60;
    return remainder ? `${hours} hr ${remainder} min` : `${hours} hr`;
  };

  const formatTrafficDelay = (seconds) => {
    if (!Number.isFinite(seconds) || seconds <= 0) return "0 min";
    return `+${formatDuration(seconds)}`;
  };

  const estimateRouteDistance = (points) => points.slice(1).reduce((total, point, index) => {
    const previous = points[index];
    const toRadians = (value) => value * Math.PI / 180;
    const latitudeDelta = toRadians(point[0] - previous[0]);
    const longitudeDelta = toRadians(point[1] - previous[1]);
    const latitudeOne = toRadians(previous[0]);
    const latitudeTwo = toRadians(point[0]);
    const haversine = Math.sin(latitudeDelta / 2) ** 2
      + Math.cos(latitudeOne) * Math.cos(latitudeTwo) * Math.sin(longitudeDelta / 2) ** 2;
    return total + 6371000 * 2 * Math.atan2(Math.sqrt(haversine), Math.sqrt(1 - haversine));
  }, 0);

  const setRouteMetrics = ({distance, duration, stops, approximate = false, traffic = null}) => {
    if (routeMetrics) routeMetrics.hidden = false;
    if (routeDistance) routeDistance.textContent = formatDistance(distance);
    if (routeDistanceLabel) routeDistanceLabel.textContent = approximate ? "Distance estimate" : "Road distance";
    if (routeTime) routeTime.textContent = formatDuration(duration);
    if (routeStops) routeStops.textContent = `${stops} district${stops === 1 ? "" : "s"}`;
    if (routeTraffic) routeTraffic.hidden = !traffic;
    if (routeTrafficValue) routeTrafficValue.textContent = traffic ? `${traffic.level} · ${formatTrafficDelay(traffic.delaySeconds)}` : "—";
  };

  const clearRouteMetrics = () => {
    if (routeMetrics) routeMetrics.hidden = true;
    if (routeDistance) routeDistance.textContent = "—";
    if (routeDistanceLabel) routeDistanceLabel.textContent = "Road distance";
    if (routeTime) routeTime.textContent = "—";
    if (routeStops) routeStops.textContent = "—";
    if (routeTraffic) routeTraffic.hidden = true;
    if (routeTrafficValue) routeTrafficValue.textContent = "—";
  };

  const initialiseLeafletMap = () => {
    if (!routeMapElement) return;
    if (!window.L) {
      setMapState("Map unavailable");
      routeMapElement.textContent = "The route map could not load. Check your connection and try again.";
      return;
    }
    travelMap = window.L.map(routeMapElement, {zoomControl: true, preferCanvas: true}).setView([1.3733, 32.2903], 7);
    const streetLayer = window.L.tileLayer("https://tile.openstreetmap.org/{z}/{x}/{y}.png", {
      maxZoom: 19,
      attribution: "&copy; OpenStreetMap contributors",
    });
    const streetFallbackLayer = window.L.tileLayer("https://{s}.tile.openstreetmap.de/{z}/{x}/{y}.png", {
      maxZoom: 19,
      subdomains: ["a", "b", "c"],
      attribution: "&copy; OpenStreetMap contributors",
    });
    const satelliteLayer = window.L.tileLayer("https://server.arcgisonline.com/ArcGIS/rest/services/World_Imagery/MapServer/tile/{z}/{y}/{x}", {
      maxZoom: 19,
      attribution: "&copy; Esri, Maxar, Earthstar Geographics",
    });
    satelliteLayer.addTo(travelMap);
    let streetFallbackActive = false;
    streetLayer.on("tileerror", () => {
      if (!travelMap.hasLayer(streetLayer) || streetFallbackActive) return;
      streetFallbackActive = true;
      streetFallbackLayer.addTo(travelMap);
      setMapState("Street map fallback active");
    });
    travelMap.on("baselayerchange", (event) => {
      if (event.name === "Street map" && streetFallbackActive) streetFallbackLayer.addTo(travelMap);
      if (event.name !== "Street map") streetFallbackLayer.remove();
    });
    window.L.control.zoom({position: "bottomright"}).addTo(travelMap);
    window.L.control.layers(
      {"Street map": streetLayer, "Satellite": satelliteLayer},
      {position: "topright", collapsed: false},
    ).addTo(travelMap);
    window.setTimeout(() => travelMap.invalidateSize(), 100);
  };

  const initialiseTravelMap = () => {
    if (!routeMapElement) return;
    initialiseLeafletMap();
  };

  const clearTravelMap = () => {
    if (!travelMap) return;
    routeRequestController?.abort();
    routeRequestController = null;
    routeRenderToken += 1;
    travelMapLayer?.remove();
    travelMapDepth?.remove();
    travelMapLine?.remove();
    travelMapUnderlay?.remove();
    travelMapMarkers.forEach((marker) => marker.remove());
    travelMapLayer = null;
    travelMapDepth = null;
    travelMapLine = null;
    travelMapUnderlay = null;
    travelMapMarkers = [];
    travelMap.setView([1.3733, 32.2903], 7);
    if (routeMapLabels) routeMapLabels.hidden = true;
    clearRouteMetrics();
    setMapState("Waiting for a route");
  };

  const drawRoadRoute = (roadPoints) => {
    travelMapLine?.remove();
    travelMapDepth?.remove();
    travelMapUnderlay?.remove();
    travelMapDepth = window.L.polyline(roadPoints, {
      className: "travel-route-depth",
      color: "#083f58",
      weight: 15,
      opacity: .52,
      lineCap: "round",
      lineJoin: "round",
    }).addTo(travelMap);
    travelMapUnderlay = window.L.polyline(roadPoints, {
      className: "travel-route-underlay",
      color: "#fff",
      weight: 10,
      opacity: .86,
      lineCap: "round",
      lineJoin: "round",
    }).addTo(travelMap);
    travelMapLine = window.L.polyline(roadPoints, {
      className: "travel-journey-highlight",
      color: "#168bb5",
      dashArray: "10 8",
      weight: 5,
      opacity: .98,
    }).addTo(travelMap);
    travelMap.fitBounds(window.L.latLngBounds(roadPoints).pad(.12));
  };

  const renderLeafletTravelMap = (result) => {
    const featureByName = new Map((result.route_map?.features || []).map((feature) => [
      feature.properties?.route_name || feature.properties?.name,
      feature,
    ]));
    const routePoints = [];
    travelMapLayer = window.L.layerGroup().addTo(travelMap);
    result.route.forEach((name, index) => {
      const feature = featureByName.get(name);
      if (!feature) return;
      const layer = window.L.geoJSON(feature, {
        style: {
          color: index === 0 || index === result.route.length - 1 ? "#d71920" : "#168bb5",
          fillColor: index === 0 || index === result.route.length - 1 ? "#f08b8f" : "#65cce9",
          fillOpacity: .24,
          weight: 2,
        },
      });
      travelMapLayer.addLayer(layer);
      const center = layer.getBounds().getCenter();
      const point = [center.lat, center.lng];
      routePoints.push(point);
      const isStart = index === 0;
      const isDestination = index === result.route.length - 1;
      const marker = isStart || isDestination
        ? window.L.marker(point, {
          icon: window.L.divIcon({
            className: `travel-map-pin${isDestination ? " destination" : ""}`,
            html: "<span>•</span>",
            iconSize: [30, 30],
            iconAnchor: [15, 30],
          }),
        }).addTo(travelMap)
        : window.L.circleMarker(point, {
          radius: 4,
          color: "#168bb5",
          fillColor: "#fff",
          fillOpacity: 1,
          weight: 3,
        }).addTo(travelMap);
      marker.bindTooltip(`${index === 0 ? "Start · " : index === result.route.length - 1 ? "Destination · " : "District · "}${name}`);
      travelMapMarkers.push(marker);
    });
    if (routePoints.length > 1) {
      travelMapDepth = window.L.polyline(routePoints, {
        className: "travel-route-depth",
        color: "#083f58",
        weight: 14,
        opacity: .5,
        lineCap: "round",
        lineJoin: "round",
      }).addTo(travelMap);
      travelMapLine = window.L.polyline(routePoints, {
        className: "travel-journey-highlight",
        color: "#167ca4",
        dashArray: "10 8",
        weight: 5,
        opacity: .95,
      }).addTo(travelMap);
    }
    if (routePoints.length) travelMap.fitBounds(window.L.latLngBounds(routePoints).pad(.2));
    const requestToken = ++routeRenderToken;
    setMapState("Finding the best available road route…");
    if (routePoints.length < 2) {
      setRouteMetrics({distance: Number.NaN, duration: Number.NaN, stops: result.route.length});
      setMapState(`${result.route.length} district${result.route.length === 1 ? "" : "s"} in corridor`);
      return;
    }
    const googleTraffic = result.google_traffic;
    if (googleTraffic?.road_points?.length > 1) {
      drawRoadRoute(googleTraffic.road_points);
      setRouteMetrics({
        distance: Number(googleTraffic.distance_meters),
        duration: Number(googleTraffic.duration_seconds),
        stops: result.route.length,
        traffic: {
          level: googleTraffic.traffic_level || "Live",
          delaySeconds: Number(googleTraffic.traffic_delay_seconds),
        },
      });
      setMapState(`Google traffic · ${googleTraffic.traffic_level || "live conditions"}`);
      return;
    }
    const routingPoints = [currentGpsPosition || routePoints[0], routePoints[routePoints.length - 1]];
    const coordinates = routingPoints.map(([latitude, longitude]) => `${longitude},${latitude}`).join(";");
    const controller = new AbortController();
    routeRequestController = controller;
    const timeoutId = window.setTimeout(() => controller.abort(), 12000);
    fetch(`https://router.project-osrm.org/route/v1/driving/${coordinates}?alternatives=false&overview=full&geometries=geojson&steps=false`, {signal: controller.signal})
      .then((response) => {
        if (!response.ok) throw new Error("The road-routing service is unavailable.");
        return response.json();
      })
      .then((data) => {
        if (requestToken !== routeRenderToken) return;
        if (!data.routes?.[0]?.geometry?.coordinates?.length) throw new Error("No road route was found.");
        const roadPoints = data.routes[0].geometry.coordinates.map(([longitude, latitude]) => [latitude, longitude]);
        travelMapLine?.remove();
        travelMapDepth?.remove();
        travelMapUnderlay?.remove();
        travelMapDepth = window.L.polyline(roadPoints, {
          className: "travel-route-depth",
          color: "#083f58",
          weight: 15,
          opacity: .52,
          lineCap: "round",
          lineJoin: "round",
        }).addTo(travelMap);
        travelMapUnderlay = window.L.polyline(roadPoints, {
          className: "travel-route-underlay",
          color: "#fff",
          weight: 10,
          opacity: .86,
          lineCap: "round",
          lineJoin: "round",
        }).addTo(travelMap);
        travelMapLine = window.L.polyline(roadPoints, {
          className: "travel-journey-highlight",
          color: "#168bb5",
          dashArray: "10 8",
          weight: 5,
          opacity: .98,
        }).addTo(travelMap);
        travelMap.fitBounds(window.L.latLngBounds(roadPoints).pad(.12));
        setRouteMetrics({distance: data.routes[0].distance, duration: data.routes[0].duration, stops: result.route.length});
        const trafficFallback = result.traffic_provider === "Google"
          ? "Google traffic unavailable"
          : "live traffic not configured";
        setMapState(`Road route · ${trafficFallback}`);
      })
      .catch((error) => {
        if (error.name === "AbortError" || requestToken !== routeRenderToken) return;
        const estimatedDistance = estimateRouteDistance(routingPoints) * 1.25;
        setRouteMetrics({
          distance: estimatedDistance,
          duration: estimatedDistance / (35 * 1000) * 3600,
          stops: result.route.length,
          approximate: true,
        });
        setMapState("Road service unavailable · approximate route");
      })
      .finally(() => {
        window.clearTimeout(timeoutId);
        if (routeRequestController === controller) routeRequestController = null;
      });
  };

  const setRouteLabels = (result) => {
    if (routeMapLabels) routeMapLabels.hidden = false;
    if (routeMapFrom) routeMapFrom.textContent = result.origin || result.route[0];
    if (routeMapTo) routeMapTo.textContent = result.destination || result.route[result.route.length - 1];
  };

  const renderTravelMap = (result) => {
    if (!travelMap || !result?.route?.length) return;
    clearTravelMap();
    setRouteLabels(result);
    renderLeafletTravelMap(result);
  };

  const updatePreciseLocation = (latitude, longitude, accuracy) => {
    if (!travelMap || !window.L) return;
    const position = [latitude, longitude];
    if (!userLocationMarker) {
      userLocationMarker = window.L.marker(position, {
        zIndexOffset: 1000,
        icon: window.L.divIcon({
          className: "travel-user-location-pin",
          html: "<span></span>",
          iconSize: [26, 26],
          iconAnchor: [13, 13],
        }),
      }).addTo(travelMap).bindTooltip("Your precise location", {direction: "top", offset: [0, -10]});
    } else {
      userLocationMarker.setLatLng(position);
    }
    if (!userAccuracyCircle) {
      userAccuracyCircle = window.L.circle(position, {
        className: "travel-user-accuracy",
        radius: Math.max(accuracy || 0, 8),
        color: "#168bb5",
        weight: 1,
        opacity: .5,
        fillColor: "#55c9ed",
        fillOpacity: .12,
      }).addTo(travelMap);
    } else {
      userAccuracyCircle.setLatLng(position);
      userAccuracyCircle.setRadius(Math.max(accuracy || 0, 8));
    }
    userLocationTrail.push(position);
    if (userLocationTrail.length > 60) userLocationTrail.shift();
    userLocationTrailLine?.remove();
    if (userLocationTrail.length > 1) {
      userLocationTrailLine = window.L.polyline(userLocationTrail, {
        className: "travel-location-trail",
        color: "#45c7ee",
        weight: 4,
        opacity: .85,
        dashArray: "3 8",
        lineCap: "round",
      }).addTo(travelMap);
    }
    if (!travelMapLine && !travelMapLayer) travelMap.flyTo(position, 15, {duration: .8});
  };

  const setFullscreenState = (enabled) => {
    routeMapShell?.classList.toggle("is-fullscreen", enabled);
    document.body.classList.toggle("travel-map-fullscreen", enabled);
    if (fullscreenButton) {
      fullscreenButton.textContent = enabled ? "Exit full map" : "Full map";
      fullscreenButton.setAttribute("aria-pressed", String(enabled));
    }
    window.setTimeout(() => travelMap?.invalidateSize(), 120);
  };

  const toggleFullscreenMap = async () => {
    if (!routeMapShell) return;
    if (document.fullscreenElement === routeMapShell) {
      await document.exitFullscreen?.();
      return;
    }
    if (document.fullscreenElement) await document.exitFullscreen?.();
    try {
      if (routeMapShell.requestFullscreen) await routeMapShell.requestFullscreen();
      else setFullscreenState(!routeMapShell.classList.contains("is-fullscreen"));
    } catch (error) {
      setFullscreenState(!routeMapShell.classList.contains("is-fullscreen"));
    }
  };

  async function handleTravelSubmit(event) {
    event.preventDefault();
    const formData = new FormData(travelForm);
    const originArea = formData.get("origin_area");
    const destinationArea = formData.get("destination_area");
    if (!originArea) {
      setStatus("Use GPS or choose the district where your journey starts.", "error");
      originSelect?.focus();
      return;
    }
    if (!destinationArea) {
      setStatus("Choose the district you are travelling to before calculating the route.", "error");
      destinationSelect?.focus();
      return;
    }
    if (originArea === destinationArea) {
      setStatus("Choose a different destination district so the distance can be calculated.", "error");
      destinationSelect?.focus();
      return;
    }
    try {
      setStatus("Preparing your travel safety watch…");
      const {browser, notice} = await optionalTravelSubscription();
      const result = await postJson(travelUrl, {
        ...browser,
        area_ids: savedAreaIds,
        origin_area: originArea,
        destination_area: destinationArea,
        start_latitude: currentGpsPosition?.[0] ?? "",
        start_longitude: currentGpsPosition?.[1] ?? "",
      });
      renderActiveAreas(savedAreaIds);
      renderTravelMap(result);
      if (travelResult) {
        travelResult.hidden = false;
        travelResult.replaceChildren();
        const heading = document.createElement("strong");
        heading.textContent = "Estimated alert corridor";
        const route = document.createElement("p");
        route.textContent = result.route.join("  →  ");
        travelResult.append(heading, route);
      }
      if (stopTravelButton) stopTravelButton.hidden = !result.watch_active;
      const routeMessage = notice ? `${result.message} ${notice}` : result.message;
      setStatus(routeMessage, result.watch_active ? "success" : "error");
    } catch (error) {
      setStatus(readablePushError(error, "The travel watch could not be started."), "error");
    }
  }

  gpsButton?.addEventListener("click", startGps);
  travelForm?.addEventListener("submit", handleTravelSubmit);

  if ("serviceWorker" in navigator) {
    const localHost = ["localhost", "127.0.0.1", "[::1]"].includes(window.location.hostname);
    const secureOrigin = window.isSecureContext || localHost;
    if (!secureOrigin) {
      serviceWorkerError = "Browser alerts require HTTPS (or localhost) and a supported browser.";
      if (saveAreasButton) saveAreasButton.disabled = true;
      setStatus(serviceWorkerError, "error");
    } else {
      serviceWorkerPromise = navigator.serviceWorker.register("/service-worker.js", {
        scope: "/",
        updateViaCache: "none",
      })
        .then(() => navigator.serviceWorker.ready)
        .then((value) => {
          registration = value;
          return value;
        })
        .catch((error) => {
          console.error("Public alert service worker registration failed.", error);
          serviceWorkerError = "Browser alerts could not start. Use HTTPS, then reload this page.";
          if (saveAreasButton) saveAreasButton.disabled = true;
          setStatus(serviceWorkerError, "error");
          return null;
        });
      serviceWorkerPromise.then((value) => {
        if (value) return loadPreferences();
        return null;
      }).catch((error) => {
        console.error("Public alert preferences could not be loaded.", error);
        setStatus("Your saved alert places could not be loaded. You can still choose and subscribe to districts.", "error");
      });
    }
    navigator.serviceWorker.addEventListener("message", (event) => {
      if (event.data?.type === "PUBLIC_AREA_ALERT") showCriticalAlert(event.data.payload);
    });
  } else {
    serviceWorkerError = "This browser does not support background safety alerts.";
    if (saveAreasButton) saveAreasButton.disabled = true;
    setStatus(serviceWorkerError, "error");
  }

  areaOptions.forEach((option) => {
    option.addEventListener("click", () => {
      if (option.tagName === "BUTTON") setAreaSelected(option, !isAreaSelected(option));
      renderActiveAreas(areaOptions.filter(isAreaSelected).map(areaId));
    });
  });
  areaSearch?.addEventListener("input", refreshAreaOptions);
  refreshAreaOptions();
  try {
    initialiseTravelMap();
  } catch (error) {
    console.error("The travel map could not be initialized.", error);
    setMapState("Map unavailable");
  }
  fullscreenButton?.addEventListener("click", toggleFullscreenMap);
  document.addEventListener("fullscreenchange", () => setFullscreenState(document.fullscreenElement === routeMapShell));
  document.addEventListener("keydown", (event) => {
    if (event.key === "Escape" && routeMapShell?.classList.contains("is-fullscreen") && !document.fullscreenElement) setFullscreenState(false);
  });
  window.addEventListener("beforeunload", stopGps);

  saveAreasButton?.addEventListener("click", async () => {
    const areaIds = areaOptions.filter(isAreaSelected).map(areaId);
    if (!areaIds.length) {
      setStatus("Choose at least one district first.", "error");
      return;
    }
    try {
      setStatus("Saving your notification places…");
      const browser = await ensureSubscription();
      const result = await postJson(subscribeUrl, {...browser, area_ids: areaIds});
      savedAreaIds = [...areaIds];
      renderActiveAreas(areaIds);
      setStatus(`Alerts are active for ${result.areas.length} district${result.areas.length === 1 ? "" : "s"}.`, "success");
    } catch (error) {
      setStatus(readablePushError(error, "Notification places could not be saved."), "error");
    }
  });

  stopTravelButton?.addEventListener("click", async () => {
    try {
      const browser = await ensureSubscription();
      await postJson(travelStopUrl, browser);
      clearTravelMap();
      travelResult.hidden = true;
      stopTravelButton.hidden = true;
      await loadPreferences();
      setStatus("Travel watch stopped. Your saved district alerts remain active.", "success");
    } catch (error) {
      setStatus(error.message || "The travel watch could not be stopped.", "error");
    }
  });
})();
