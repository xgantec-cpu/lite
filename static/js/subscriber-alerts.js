(() => {
  const page = document.querySelector("[data-subscriber-alerts]");
  if (!page) return;

  const publicKey = page.dataset.publicKey || "";
  const subscribeUrl = page.dataset.subscribeUrl;
  const preferencesUrl = page.dataset.preferencesUrl;
  const removeAreaUrl = page.dataset.removeAreaUrl;
  const travelUrl = page.dataset.travelUrl;
  const travelLocationUrl = page.dataset.travelLocationUrl;
  const travelPlaceSearchUrl = page.dataset.travelPlaceSearchUrl;
  const travelReverseLocationUrl = page.dataset.travelReverseLocationUrl;
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
  const destinationPlaceInput = travelForm?.querySelector("[data-destination-place]");
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
  const mapPinButton = page.querySelector("[data-map-pin-mode]");
  const destinationPinButton = page.querySelector("[data-map-destination-mode]");
  const mapThemeButton = page.querySelector("[data-map-theme-toggle]");
  const mapPinStatus = page.querySelector("[data-map-pin-status]");
  const mapPinConfirm = page.querySelector("[data-map-pin-confirm-panel]");
  const mapPinConfirmTitle = page.querySelector("[data-map-pin-confirm-title]");
  const mapPinConfirmText = page.querySelector("[data-map-pin-confirm-text]");
  const mapPinConfirmButton = page.querySelector("[data-map-pin-confirm]");
  const mapPinUseGpsButton = page.querySelector("[data-map-pin-use-gps]");
  const mapPinCancelButton = page.querySelector("[data-map-pin-cancel]");
  const mapPlaceSearch = page.querySelector("[data-map-place-search]");
  const mapPlaceResults = page.querySelector("[data-map-place-results]");
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
  const userLocationPings = [];
  let manualLocationMarker;
  let destinationLocationMarker;
  let manualMapPosition;
  let destinationMapPosition;
  let pendingManualPin;
  let pendingDestinationPin;
  let mapPinMode = false;
  let destinationPinMode = false;
  let pendingPinType = "";
  let mapSearchLayer;
  const userLocationTrail = [];
  let routeRenderToken = 0;
  let routeRequestController;
  let travelStreetLayer;
  let travelSatelliteLayer;
  let currentGpsPosition;
  let plannedRoutePoints = [];
  let currentGpsAreaName = "";
  let currentGpsAreaId = "";
  let locationLookupPending = false;
  let originAreaResolved = false;
  let districtMapFeatures = [];
  let placeSearchTimer;
  let placeSearchController;

  try {
    const boundaryScript = document.getElementById("travel-district-boundaries");
    districtMapFeatures = JSON.parse(boundaryScript?.textContent || "{}").features || [];
  } catch (error) {
    districtMapFeatures = [];
  }

  const distanceBetweenPoints = (first, second) => {
    if (!first || !second) return Number.NaN;
    const toRadians = (value) => value * Math.PI / 180;
    const latitudeOne = toRadians(first[0]);
    const latitudeTwo = toRadians(second[0]);
    const latitudeDelta = latitudeTwo - latitudeOne;
    const longitudeDelta = toRadians(second[1] - first[1]);
    const haversine = Math.sin(latitudeDelta / 2) ** 2
      + Math.cos(latitudeOne) * Math.cos(latitudeTwo) * Math.sin(longitudeDelta / 2) ** 2;
    return 6371000 * 2 * Math.atan2(Math.sqrt(haversine), Math.sqrt(1 - haversine));
  };

  const setMapPinStatus = (message) => {
    if (mapPinStatus) mapPinStatus.textContent = message;
  };

  const setMapPinMode = (enabled) => {
    mapPinMode = enabled;
    if (enabled) setDestinationPinMode(false);
    if (mapPinButton) {
      mapPinButton.textContent = enabled ? "Cancel map pin" : "Pin start on map";
      mapPinButton.setAttribute("aria-pressed", String(enabled));
    }
    if (enabled) setMapPinStatus("Tap the map where your journey starts.");
    else if (!pendingManualPin) setMapPinStatus("Choose “Pin start on map”, then tap your starting point.");
  };

  const setDestinationPinMode = (enabled) => {
    destinationPinMode = enabled;
    if (enabled) setMapPinMode(false);
    if (destinationPinButton) {
      destinationPinButton.textContent = enabled ? "Cancel destination pin" : "Pin destination village";
      destinationPinButton.setAttribute("aria-pressed", String(enabled));
    }
    if (enabled) setMapPinStatus("Tap the destination map district where the village or landmark is located.");
    else if (!pendingDestinationPin && !pendingManualPin) setMapPinStatus("Choose “Pin start on map”, then tap your starting point.");
  };

  const setManualLocationMarker = (position) => {
    if (!travelMap || !window.L) return;
    const icon = window.L.divIcon({
      className: "travel-origin-location-pin",
      html: "<span></span>",
      iconSize: [32, 40],
      iconAnchor: [16, 40],
    });
    if (!manualLocationMarker) {
      manualLocationMarker = window.L.marker(position, {icon, zIndexOffset: 900})
        .addTo(travelMap)
        .bindTooltip("Selected starting point", {direction: "top", offset: [0, -34]});
    } else {
      manualLocationMarker.setLatLng(position);
    }
  };

  const setDestinationLocationMarker = (position, placeName = "Selected destination") => {
    if (!travelMap || !window.L) return;
    const icon = window.L.divIcon({
      className: "travel-destination-location-pin",
      html: "<span></span>",
      iconSize: [32, 40],
      iconAnchor: [16, 40],
    });
    if (!destinationLocationMarker) {
      destinationLocationMarker = window.L.marker(position, {icon, zIndexOffset: 850})
        .addTo(travelMap)
        .bindTooltip(placeName, {direction: "top", offset: [0, -14]});
    } else {
      destinationLocationMarker.setLatLng(position);
      destinationLocationMarker.setTooltipContent(placeName);
    }
  };

  const resetMapPinConfirmationUi = () => {
    if (mapPinConfirmTitle) mapPinConfirmTitle.textContent = "Confirm this starting point";
    if (mapPinConfirmButton) mapPinConfirmButton.textContent = "Use tapped point";
    if (mapPinUseGpsButton) mapPinUseGpsButton.hidden = true;
  };

  const hideMapPinConfirmation = () => {
    pendingManualPin = null;
    pendingDestinationPin = null;
    pendingPinType = "";
    if (mapPinConfirm) mapPinConfirm.hidden = true;
    resetMapPinConfirmationUi();
  };

  const cancelMapPinConfirmation = () => {
    const wasDestination = pendingPinType === "destination";
    hideMapPinConfirmation();

    if (wasDestination) {
      destinationMapPosition = null;
      if (destinationPlaceInput) destinationPlaceInput.value = "";
      destinationLocationMarker?.remove();
      destinationLocationMarker = null;
      return;
    }

    manualMapPosition = null;
    manualLocationMarker?.remove();
    manualLocationMarker = null;
  };

  const confirmManualMapPoint = () => {
    if (pendingPinType === "destination" && pendingDestinationPin) {
      destinationMapPosition = pendingDestinationPin.position;
      if (destinationPlaceInput) destinationPlaceInput.value = pendingDestinationPin.place;
      setDestinationLocationMarker(destinationMapPosition, pendingDestinationPin.place);
      const destinationName = destinationSelect?.selectedOptions?.[0]?.textContent?.trim() || "the selected district";
      hideMapPinConfirmation();
      setMapPinStatus(`Destination confirmed: ${pendingDestinationPin.place} in ${destinationName}. Submit the form to calculate the route.`);
      setStatus(`Destination confirmed at ${pendingDestinationPin.place}.`, "success");
      return;
    }
    if (!pendingManualPin) return;
    manualMapPosition = pendingManualPin.position;
    if (originSelect) originSelect.value = String(pendingManualPin.area.id);
    originAreaResolved = true;
    const areaName = pendingManualPin.area.name;
    hideMapPinConfirmation();
    setMapPinStatus(`Starting point confirmed in ${areaName}. Submit the form to calculate the route.`);
    setStatus(`Map starting point confirmed in ${areaName}.`, "success");
    destinationSelect?.focus();
  };

  const useGpsMapPoint = async () => {
    if (!currentGpsPosition) return;
    if (!currentGpsAreaId && travelLocationUrl) {
      await resolveOriginArea(currentGpsPosition[0], currentGpsPosition[1]);
    }
    if (!currentGpsAreaId) {
      setStatus("GPS could not identify a supported starting district. Choose one manually.", "error");
      return;
    }
    manualMapPosition = [...currentGpsPosition];
    if (currentGpsAreaId && originSelect) originSelect.value = currentGpsAreaId;
    setManualLocationMarker(manualMapPosition);
    hideMapPinConfirmation();
    setMapPinStatus("GPS starting point selected. Submit the form to calculate the route.");
    setStatus("Your GPS position will be used as the starting point.", "success");
  };

  const handleMapPointSelection = async (latLng) => {
    const position = [Number(latLng.lat), Number(latLng.lng)];
    setManualLocationMarker(position);
    setMapPinMode(false);
    pendingPinType = "start";
    setMapPinStatus("Checking the selected point…");
    if (!travelLocationUrl) {
      setStatus("The selected map point could not be verified.", "error");
      return;
    }
    try {
      const result = await postJson(travelLocationUrl, {latitude: position[0], longitude: position[1]});
      pendingManualPin = {position, area: result.area};
      const gpsDistance = distanceBetweenPoints(currentGpsPosition, position);
      const gpsSummary = currentGpsPosition
        ? ` Your GPS point is about ${formatDistance(gpsDistance)} away${currentGpsAreaName ? ` in ${currentGpsAreaName}` : ""}.`
        : " GPS is not active on this device.";
      if (mapPinConfirmText) {
        mapPinConfirmText.textContent = `This point is in ${result.area.name}.${gpsSummary} Confirm that this is your journey starting point.`;
      }
      if (mapPinConfirmTitle) mapPinConfirmTitle.textContent = "Confirm this starting point";
      if (mapPinConfirmButton) mapPinConfirmButton.textContent = "Use tapped point";
      if (mapPinUseGpsButton) mapPinUseGpsButton.hidden = !currentGpsPosition;
      if (mapPinConfirm) mapPinConfirm.hidden = false;
      setMapPinStatus("Confirm the selected starting point below the map.");
    } catch (error) {
      setStatus(error.message || "The selected point is outside the supported districts.", "error");
      setMapPinStatus("Choose “Pin start on map” and tap a supported district.");
    }
  };

  const handleDestinationPointSelection = async (latLng) => {
    const destinationAreaId = destinationSelect?.value;
    if (!destinationAreaId) {
      setStatus("Choose the destination district before pinning a village.", "error");
      setDestinationPinMode(false);
      return;
    }
    const position = [Number(latLng.lat), Number(latLng.lng)];
    setDestinationLocationMarker(position);
    setDestinationPinMode(false);
    setMapPinStatus("Checking the selected village or landmark…");
    try {
      const areaResult = await postJson(travelLocationUrl, {latitude: position[0], longitude: position[1]});
      if (String(areaResult.area?.id) !== String(destinationAreaId)) {
        throw new Error(`Tap inside ${destinationSelect.selectedOptions[0].textContent.trim()} to choose its village or landmark.`);
      }
      let reverseResult = {place: "Selected map point"};
      if (travelReverseLocationUrl) {
        try {
          reverseResult = await postJson(travelReverseLocationUrl, {latitude: position[0], longitude: position[1]});
        } catch (error) {
          setStatus("The map point is valid, but its village name could not be loaded. You can still confirm the point.", "error");
        }
      }
      pendingPinType = "destination";
      pendingDestinationPin = {position, place: reverseResult.place || "Selected map point"};
      pendingManualPin = null;
      if (mapPinConfirmTitle) mapPinConfirmTitle.textContent = "Confirm this destination village";
      if (mapPinConfirmText) mapPinConfirmText.textContent = `${pendingDestinationPin.place} is inside ${destinationSelect.selectedOptions[0].textContent.trim()}. Confirm that this is where you are travelling.`;
      if (mapPinConfirmButton) mapPinConfirmButton.textContent = "Use destination village";
      if (mapPinUseGpsButton) mapPinUseGpsButton.hidden = true;
      if (mapPinConfirm) mapPinConfirm.hidden = false;
      setMapPinStatus("Confirm the destination village below the map.");
    } catch (error) {
      setStatus(error.message || "The selected point is outside the destination district.", "error");
      setMapPinStatus("Choose “Pin destination village” and tap inside the destination district.");
    }
  };

  const placeCategoryIcon = (result) => {
    const value = `${result.category || ""} ${result.name || ""}`.toLocaleLowerCase();
    if (/(coffee|cafe|restaurant|bakery)/.test(value)) return "☕";
    if (/(fuel|petrol|gas)/.test(value)) return "⛽";
    if (/(hospital|clinic|health)/.test(value)) return "✚";
    if (/(police|station)/.test(value)) return "⚑";
    if (/(hotel|lodging|guest)/.test(value)) return "⌂";
    if (/(shop|market|mall)/.test(value)) return "▦";
    return "⌖";
  };

  const placeSearchPoint = () => {
    if (currentGpsPosition) return currentGpsPosition;
    if (destinationMapPosition) return destinationMapPosition;
    if (plannedRoutePoints.length) return plannedRoutePoints[Math.floor(plannedRoutePoints.length / 2)];
    const center = travelMap?.getCenter?.();
    return center ? [center.lat, center.lng] : null;
  };

  const hidePlaceSearchResults = () => {
    mapPlaceResults?.replaceChildren();
    if (mapPlaceResults) mapPlaceResults.hidden = true;
  };

  const selectPlaceSearchResult = (result) => {
    const latitude = Number(result.latitude);
    const longitude = Number(result.longitude);
    if (!Number.isFinite(latitude) || !Number.isFinite(longitude)) return;
    const position = [latitude, longitude];
    const areaName = result.area?.name || "";
    if (areaName && destinationSelect) {
      const option = [...destinationSelect.options].find(
        (item) => item.textContent.trim().toLocaleLowerCase() === areaName.toLocaleLowerCase(),
      );
      if (option && destinationSelect.value !== option.value) {
        destinationSelect.value = option.value;
        destinationSelect.dispatchEvent(new Event("change", {bubbles: true}));
      }
    }
    setDestinationPinMode(false);
    destinationMapPosition = position;
    const placeName = result.name || result.display_name || "Selected route place";
    if (destinationPlaceInput) destinationPlaceInput.value = placeName;
    setDestinationLocationMarker(position, placeName);
    if (travelMap) travelMap.flyTo(position, 16, {duration: .8});
    if (mapPlaceSearch) mapPlaceSearch.value = placeName;
    hidePlaceSearchResults();
    setMapPinStatus(`Route place selected${areaName ? ` in ${areaName}` : ""}. Submit the form to calculate the route.`);
    setMapState(`Viewing ${placeName}`);
    setStatus(`${placeName} selected${areaName ? ` in ${areaName}` : ""}.`, "success");
  };

  const renderPlaceSearchResults = (results) => {
    if (!mapPlaceResults) return;
    mapPlaceResults.replaceChildren();
    results.slice(0, 8).forEach((result) => {
      const option = document.createElement("button");
      option.type = "button";
      option.className = "travel-map-search-result travel-place-result";
      option.setAttribute("role", "option");

      const icon = document.createElement("span");
      icon.className = "travel-place-result-icon";
      icon.setAttribute("aria-hidden", "true");
      icon.textContent = placeCategoryIcon(result);
      const copy = document.createElement("span");
      copy.className = "travel-place-result-copy";
      const name = document.createElement("strong");
      name.textContent = result.name || "Map place";
      const address = document.createElement("small");
      address.textContent = result.display_name || result.category || "Listed on the map";
      copy.append(name, address);
      option.append(icon, copy);
      option.addEventListener("click", () => selectPlaceSearchResult(result));
      mapPlaceResults.appendChild(option);
    });
    mapPlaceResults.hidden = results.length === 0;
  };

  const searchNearbyPlaces = async () => {
    if (!mapPlaceSearch || !mapPlaceResults || !travelPlaceSearchUrl) return;
    const query = mapPlaceSearch.value.trim();
    if (query.length < 2) {
      hidePlaceSearchResults();
      return;
    }
    placeSearchController?.abort();
    placeSearchController = new AbortController();
    const params = new URLSearchParams({q: query});
    const point = placeSearchPoint();
    if (point) {
      params.set("lat", String(point[0]));
      params.set("lon", String(point[1]));
    }
    mapPlaceResults.replaceChildren();
    const loading = document.createElement("span");
    loading.className = "travel-map-search-loading";
    loading.textContent = "Searching listed map places…";
    mapPlaceResults.appendChild(loading);
    mapPlaceResults.hidden = false;
    try {
      const response = await fetch(`${travelPlaceSearchUrl}?${params.toString()}`, {
        credentials: "same-origin",
        headers: {Accept: "application/json"},
        signal: placeSearchController.signal,
      });
      const payload = await response.json();
      if (!response.ok) throw new Error(payload.error || "Nearby places could not be loaded.");
      renderPlaceSearchResults(payload.results || []);
      if (!(payload.results || []).length) {
        const empty = document.createElement("span");
        empty.className = "travel-map-search-loading";
        empty.textContent = "No mapped places found. Try “cafe”, “fuel”, or “hospital”.";
        mapPlaceResults.appendChild(empty);
        mapPlaceResults.hidden = false;
      }
    } catch (error) {
      if (error.name === "AbortError") return;
      hidePlaceSearchResults();
      setStatus(error.message || "Nearby places could not be loaded.", "error");
    }
  };

  const queuePlaceSearch = () => {
    window.clearTimeout(placeSearchTimer);
    placeSearchTimer = window.setTimeout(searchNearbyPlaces, 350);
  };

  const focusDistrictOnMap = (feature) => {
    if (!travelMap || !window.L || !feature) return;
    mapSearchLayer?.remove();
    mapSearchLayer = window.L.geoJSON(feature, {
      style: {
        color: "#ffd166",
        weight: 4,
        opacity: .98,
        fillColor: "#168bb5",
        fillOpacity: .2,
        dashArray: "8 6",
      },
    }).addTo(travelMap);
    const bounds = mapSearchLayer.getBounds();
    travelSatelliteLayer?.remove();
    travelStreetLayer?.addTo(travelMap);
    if (bounds.isValid()) travelMap.flyToBounds(bounds.pad(.16), {duration: .8, maxZoom: 13});
    setMapState(`Viewing ${feature.properties?.name || "selected district"}`);
  };

  const handleDestinationDistrictChange = () => {
    destinationMapPosition = null;
    pendingDestinationPin = null;
    if (destinationPlaceInput) destinationPlaceInput.value = "";
    destinationLocationMarker?.remove();
    destinationLocationMarker = null;
    const selectedName = destinationSelect?.selectedOptions?.[0]?.textContent?.trim() || "";
    const feature = districtMapFeatures.find((item) => (item.properties?.name || "").toLocaleLowerCase() === selectedName.toLocaleLowerCase());
    if (feature) focusDistrictOnMap(feature);
    if (destinationPinButton) destinationPinButton.disabled = !destinationSelect?.value;
    if (destinationSelect?.value) {
      setDestinationPinMode(true);
      setMapPinStatus(`Destination district shown: ${selectedName}. Pin a village on the map.`);
    } else if (!mapPinMode) {
      setMapPinStatus("Choose “Pin start on map”, then tap your starting point.");
    }
  };

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
      currentGpsAreaName = result.area.name || "";
      currentGpsAreaId = String(result.area.id);
      originAreaResolved = true;
      updateCurrentLocationMarkerDetails();
      setStatus(`${result.message} Route distance will be calculated after you choose the destination.`, "success");
      destinationSelect?.focus();
    } catch (error) {
      setStatus(error.message || "The starting district could not be identified. Choose it manually.", "error");
    } finally {
      locationLookupPending = false;
    }
  };

  const updateGpsUi = (message, state = "") => {
    const currentState = state || "standby";
    if (gpsStatus) {
      gpsStatus.textContent = message;
      gpsStatus.dataset.state = currentState;
    }
    if (gpsIndicator) {
      gpsIndicator.textContent = currentState === "live" ? "GPS live" : currentState === "requesting" ? "Requesting GPS" : currentState === "error" ? "GPS unavailable" : "GPS standby";
      gpsIndicator.dataset.state = currentState;
    }
    if (gpsButton) {
      gpsButton.textContent = currentState === "live" ? "Stop live GPS view" : currentState === "requesting" ? "Requesting GPS permission…" : "Use GPS for live trip view";
      gpsButton.dataset.state = currentState;
      gpsButton.setAttribute("aria-busy", String(currentState === "requesting"));
    }
  };

  const stopGps = () => {
    if (gpsWatchId !== null && navigator.geolocation) navigator.geolocation.clearWatch(gpsWatchId);
    gpsWatchId = null;
    gpsActive = false;
    if (livePosition) livePosition.hidden = true;
    updateGpsUi("Location stays on this device.", "standby");
  };

  const startGps = () => {
    if (!navigator.geolocation) {
      updateGpsUi("This browser does not provide location services.", "error");
      setStatus("Live GPS is not available in this browser.", "error");
      return;
    }
    const localHost = ["localhost", "127.0.0.1", "[::1]"].includes(window.location.hostname);
    if (window.isSecureContext === false && !localHost) {
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
    userLocationTrail.length = 0;
    userLocationPings.forEach((ping) => ping.remove());
    userLocationPings.length = 0;
    userLocationTrailLine?.remove();
    userLocationTrailLine = null;
    currentGpsAreaName = "";
    currentGpsAreaId = "";
    originAreaResolved = false;
    locationLookupPending = false;
    updateGpsUi("Requesting location permission…", "requesting");
    setStatus("Requesting GPS permission for this device…");
    const saveLocation = (latitude, longitude, accuracy) => {
      try {
        window.localStorage.setItem("rapid_response_last_location", JSON.stringify({
          latitude,
          longitude,
          accuracy,
          capturedAt: Date.now(),
        }));
      } catch (error) {}
    };
    const handlePosition = (position) => {
      const {latitude, longitude, accuracy} = position.coords;
      if (!Number.isFinite(latitude) || !Number.isFinite(longitude)) {
        handleError({code: 2});
        return;
      }
      currentGpsPosition = [latitude, longitude];
      saveLocation(latitude, longitude, accuracy || 0);
      const updated = new Date(position.timestamp || Date.now()).toLocaleTimeString([], {hour: "2-digit", minute: "2-digit"});
      if (livePosition) {
        livePosition.hidden = false;
        livePosition.textContent = `Live position ${latitude.toFixed(5)}, ${longitude.toFixed(5)} · accuracy ±${Math.round(accuracy)} m · updated ${updated}`;
      }
      const routeAdvice = updatePreciseLocation(latitude, longitude, accuracy);
      resolveOriginArea(latitude, longitude);
      updateGpsUi(`Live position updated at ${updated}. Exact coordinates stay on this device.`, "live");
      setStatus(routeAdvice?.message || "GPS is live for this trip view. Your exact location is not stored by this page.", routeAdvice?.state || "success");
    };
    const handleError = (error) => {
      gpsActive = false;
      if (gpsWatchId !== null && navigator.geolocation) navigator.geolocation.clearWatch(gpsWatchId);
      gpsWatchId = null;
      const message = error.code === 1
        ? "Location permission was denied. Enable it in browser settings, then try again."
        : error.code === 3
          ? "GPS took too long to respond. Move near a window and try again."
          : "The device could not provide a current location. Check GPS and try again.";
      updateGpsUi(message, "error");
      setMapState("GPS position unavailable");
      setStatus(message, "error");
    };
    const options = {enableHighAccuracy: true, maximumAge: 10000, timeout: 15000};
    try {
      gpsWatchId = navigator.geolocation.watchPosition(handlePosition, handleError, options);
      navigator.geolocation.getCurrentPosition(handlePosition, handleError, options);
    } catch (error) {
      handleError({code: 2});
    }
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

  const distanceToRouteSegment = (point, start, end) => {
    const earthRadius = 6371000;
    const latitudeScale = Math.cos(point[0] * Math.PI / 180);
    const project = ([latitude, longitude]) => ({
      x: earthRadius * longitude * Math.PI / 180 * latitudeScale,
      y: earthRadius * latitude * Math.PI / 180,
    });
    const projectedPoint = project(point);
    const projectedStart = project(start);
    const projectedEnd = project(end);
    const deltaX = projectedEnd.x - projectedStart.x;
    const deltaY = projectedEnd.y - projectedStart.y;
    const denominator = deltaX ** 2 + deltaY ** 2;
    const ratio = denominator ? Math.max(0, Math.min(1, ((projectedPoint.x - projectedStart.x) * deltaX + (projectedPoint.y - projectedStart.y) * deltaY) / denominator)) : 0;
    const closestX = projectedStart.x + ratio * deltaX;
    const closestY = projectedStart.y + ratio * deltaY;
    return Math.hypot(projectedPoint.x - closestX, projectedPoint.y - closestY);
  };

  const distanceToPlannedRoute = (position) => {
    if (plannedRoutePoints.length < 2) return Number.NaN;
    return plannedRoutePoints.slice(1).reduce((nearest, point, index) => Math.min(
      nearest,
      distanceToRouteSegment(position, plannedRoutePoints[index], point),
    ), Number.POSITIVE_INFINITY);
  };

  const assessRoutePosition = (position, accuracy) => {
    const routeDistance = distanceToPlannedRoute(position);
    if (!Number.isFinite(routeDistance)) return null;
    const gpsTolerance = Math.max(250, Math.min(700, Number(accuracy || 0) * 2 + 200));
    if (routeDistance > gpsTolerance) {
      setMapState(`Off planned route · ${formatDistance(routeDistance)} away`);
      return {
        message: `You are about ${formatDistance(routeDistance)} from the highlighted route. For fuel safety, return to the route or tap “Calculate route & distance” again to recalculate from your current GPS position.`,
        state: "warning",
      };
    }
    setMapState(`Near planned route · ${formatDistance(routeDistance)} from line`);
    return null;
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
    const satelliteLayer = window.L.tileLayer("https://server.arcgisonline.com/ArcGIS/rest/services/World_Imagery/MapServer/tile/{z}/{y}/{x}", {
      maxZoom: 19,
      attribution: "&copy; Esri, Maxar, Earthstar Geographics",
    });
    travelStreetLayer = streetLayer;
    travelSatelliteLayer = satelliteLayer;
    streetLayer.addTo(travelMap);
    window.L.control.zoom({position: "bottomright"}).addTo(travelMap);
    window.L.control.layers(
      {"Street map": streetLayer, "Satellite": satelliteLayer},
      {position: "topright", collapsed: false},
    ).addTo(travelMap);
    travelMap.on("click", (event) => {
      if (destinationPinMode) handleDestinationPointSelection(event.latlng);
      else if (mapPinMode) handleMapPointSelection(event.latlng);
    });
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
    plannedRoutePoints = [];
    travelMap.setView([1.3733, 32.2903], 7);
    if (routeMapLabels) routeMapLabels.hidden = true;
    clearRouteMetrics();
    setMapState("Waiting for a route");
  };

  const drawRoadRoute = (roadPoints) => {
    plannedRoutePoints = roadPoints;
    const routeUnderlayColor = routeMapShell?.classList.contains("is-dark-map") ? "#173b4c" : "#fff";
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
      color: routeUnderlayColor,
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
            className: isStart ? "travel-origin-location-pin" : "travel-destination-location-pin",
            html: "<span></span>",
            iconSize: [32, 40],
            iconAnchor: [16, 40],
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
      plannedRoutePoints = routePoints;
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
    const destinationPoint = Array.isArray(result.destination_point) && result.destination_point.length === 2
      ? result.destination_point
      : routePoints[routePoints.length - 1];
    const routingPoints = [manualMapPosition || currentGpsPosition || routePoints[0], destinationPoint];
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
        plannedRoutePoints = roadPoints;
        const routeUnderlayColor = routeMapShell?.classList.contains("is-dark-map") ? "#173b4c" : "#fff";
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
          color: routeUnderlayColor,
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
    if (routeMapTo) routeMapTo.textContent = result.destination_place
      ? `${result.destination} · ${result.destination_place}`
      : result.destination || result.route[result.route.length - 1];
  };

  const renderTravelMap = (result) => {
    if (!travelMap || !result?.route?.length) return;
    clearTravelMap();
    setRouteLabels(result);
    renderLeafletTravelMap(result);
  };

  const districtLocationDetails = (areaName) => {
    const normalizedName = (areaName || "").trim().toLocaleLowerCase();
    if (normalizedName === "masaka" || normalizedName === "masaka city") {
      return {icon: "◎", label: "Equator area"};
    }
    return {icon: "⌖", label: "District area"};
  };

  const updateCurrentLocationMarkerDetails = () => {
    if (!userLocationMarker) return;
    const areaName = currentGpsAreaName || "Current area";
    const detail = districtLocationDetails(currentGpsAreaName);
    const popup = document.createElement("div");
    popup.className = "travel-location-popup";
    const heading = document.createElement("strong");
    heading.className = "travel-location-popup-heading";
    const icon = document.createElement("span");
    icon.className = "travel-location-popup-icon";
    icon.setAttribute("aria-hidden", "true");
    icon.textContent = detail.icon;
    const title = document.createElement("span");
    title.textContent = areaName;
    heading.append(icon, title);
    const caption = document.createElement("small");
    caption.textContent = currentGpsAreaName ? detail.label : "Waiting for district match";
    popup.append(heading, caption);
    userLocationMarker.bindPopup(popup, {maxWidth: 220});
    userLocationMarker.bindTooltip(`${areaName} · ${detail.label}`, {direction: "top", offset: [0, -18]});
  };

  const updatePreciseLocation = (latitude, longitude, accuracy, addMovementPing = true) => {
    if (!travelMap || !window.L) return;
    const position = [latitude, longitude];
    if (addMovementPing) {
      const ping = window.L.circleMarker(position, {
        className: "travel-movement-ping",
        radius: 5,
        color: "#ffffff",
        weight: 2,
        fillColor: "#55c9ed",
        fillOpacity: .96,
        interactive: false,
      }).addTo(travelMap);
      userLocationPings.push(ping);
      if (userLocationPings.length > 60) userLocationPings.shift()?.remove();
    }
    if (!userLocationMarker) {
      userLocationMarker = window.L.marker(position, {
        zIndexOffset: 1000,
        icon: window.L.divIcon({
          className: "travel-current-location-pin",
          html: "<span></span>",
          iconSize: [26, 26],
          iconAnchor: [13, 13],
        }),
      }).addTo(travelMap);
      updateCurrentLocationMarkerDetails();
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
    return assessRoutePosition(position, accuracy);
  };

  const readStoredLocation = () => {
    try {
      const location = JSON.parse(window.localStorage.getItem("rapid_response_last_location") || "null");
      if (!location || !location.capturedAt || Date.now() - location.capturedAt > 24 * 60 * 60 * 1000) return null;
      if (!Number.isFinite(Number(location.latitude)) || !Number.isFinite(Number(location.longitude))) return null;
      return {
        latitude: Number(location.latitude),
        longitude: Number(location.longitude),
        accuracy: Number(location.accuracy) || 0,
      };
    } catch (error) {
      return null;
    }
  };

  const showDefaultLocation = (location, message) => {
    if (!location) return false;
    currentGpsPosition = [location.latitude, location.longitude];
    updatePreciseLocation(location.latitude, location.longitude, location.accuracy, false);
    if (livePosition) {
      livePosition.hidden = false;
      livePosition.textContent = `${message} ${location.latitude.toFixed(5)}, ${location.longitude.toFixed(5)}`;
    }
    updateGpsUi(message);
    setMapState("Current GPS position shown");
    resolveOriginArea(location.latitude, location.longitude);
    return true;
  };

  const restoreDefaultLocation = async () => {
    const storedLocation = readStoredLocation();
    if (storedLocation) showDefaultLocation(storedLocation, "Last approved GPS position:");
    if (!navigator.geolocation) {
      if (!storedLocation) setMapState("Use GPS to show your position");
      return;
    }
    let permissionState = "";
    try {
      permissionState = (await navigator.permissions?.query({name: "geolocation"}))?.state || "";
    } catch (error) {}
    if (permissionState !== "granted") {
      if (!storedLocation) setMapState("Use GPS to show your position");
      return;
    }
    navigator.geolocation.getCurrentPosition((position) => {
      const location = {
        latitude: position.coords.latitude,
        longitude: position.coords.longitude,
        accuracy: position.coords.accuracy || 0,
      };
      try {
        window.localStorage.setItem("rapid_response_last_location", JSON.stringify({...location, capturedAt: Date.now()}));
      } catch (error) {}
      showDefaultLocation(location, "Current GPS position:");
    }, () => {
      if (!storedLocation) setMapState("Use GPS to show your position");
    }, {enableHighAccuracy: true, maximumAge: 10000, timeout: 15000});
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

  const setMapTheme = (dark) => {
    routeMapShell?.classList.toggle("is-dark-map", dark);
    travelMapUnderlay?.setStyle({color: dark ? "#173b4c" : "#fff"});
    if (dark) {
      travelSatelliteLayer?.remove();
      travelStreetLayer?.addTo(travelMap);
    }
    if (mapThemeButton) {
      mapThemeButton.textContent = dark ? "Day map" : "Night map";
      mapThemeButton.setAttribute("aria-pressed", String(dark));
      mapThemeButton.setAttribute("aria-label", dark ? "Use day map theme" : "Use night map theme");
    }
    try {
      window.localStorage.setItem("rapid-response-travel-map-theme", dark ? "dark" : "light");
    } catch (error) {}
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
        start_latitude: (manualMapPosition || currentGpsPosition)?.[0] ?? "",
        start_longitude: (manualMapPosition || currentGpsPosition)?.[1] ?? "",
        destination_latitude: destinationMapPosition?.[0] ?? "",
        destination_longitude: destinationMapPosition?.[1] ?? "",
        destination_place: destinationPlaceInput?.value || "",
      });
      renderActiveAreas(savedAreaIds);
      renderTravelMap(result);
      if (travelResult) {
        travelResult.hidden = false;
        travelResult.replaceChildren();
        const heading = document.createElement("strong");
        heading.textContent = "Estimated alert corridor";
        const route = document.createElement("p");
        route.textContent = result.destination_place
          ? `${result.route.join("  →  ")} · Destination: ${result.destination_place}`
          : result.route.join("  →  ");
        travelResult.append(heading, route);
      }
      if (stopTravelButton) stopTravelButton.hidden = !result.watch_active;
      const routeMessage = notice ? `${result.message} ${notice}` : result.message;
      setStatus(routeMessage, result.watch_active ? "success" : "error");
    } catch (error) {
      setStatus(readablePushError(error, "The travel watch could not be started."), "error");
    }
  }

  gpsButton?.addEventListener("click", (event) => {
    event.preventDefault();
    startGps();
  });
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
    restoreDefaultLocation();
    setMapTheme(window.localStorage.getItem("rapid-response-travel-map-theme") === "dark");
  } catch (error) {
    console.error("The travel map could not be initialized.", error);
    setMapState("Map unavailable");
  }
  fullscreenButton?.addEventListener("click", toggleFullscreenMap);
  mapThemeButton?.addEventListener("click", () => setMapTheme(!routeMapShell?.classList.contains("is-dark-map")));
  mapPinButton?.addEventListener("click", () => setMapPinMode(!mapPinMode));
  destinationPinButton?.addEventListener("click", () => setDestinationPinMode(!destinationPinMode));
  destinationSelect?.addEventListener("change", handleDestinationDistrictChange);
  mapPinConfirmButton?.addEventListener("click", confirmManualMapPoint);
  mapPinUseGpsButton?.addEventListener("click", useGpsMapPoint);
  mapPinCancelButton?.addEventListener("click", () => {
    const wasDestination = destinationPinMode || pendingPinType === "destination";
    cancelMapPinConfirmation();
    if (wasDestination) setDestinationPinMode(false);
    else setMapPinMode(false);
    setMapPinStatus("Choose “Pin start on map”, then tap your starting point.");
  });
  mapPlaceSearch?.addEventListener("input", queuePlaceSearch);
  mapPlaceSearch?.addEventListener("keydown", (event) => {
    if (event.key === "Escape") {
      mapPlaceSearch.value = "";
      hidePlaceSearchResults();
    }
  });
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
