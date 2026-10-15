(function () {
  "use strict";

  document.querySelectorAll("[data-rtc-widget]").forEach(function (widget) {
    const socketPath = widget.dataset.rtcWsUrl || widget.dataset.chatWsUrlTemplate;
    const referralSelect = widget.querySelector("[data-chat-referral]");
    const answerButton = widget.querySelector("[data-rtc-answer]");
    const declineButton = widget.querySelector("[data-rtc-decline]");
    const callButton = widget.querySelector("[data-rtc-call]");
    const endButton = widget.querySelector("[data-rtc-end]");
    const muteButton = widget.querySelector("[data-rtc-mute]");
    const speakerButton = widget.querySelector("[data-rtc-speaker]");
    const status = widget.querySelector("[data-rtc-status]");
    const micStatus = widget.querySelector("[data-rtc-mic]");
    const remoteAudio = widget.querySelector("[data-rtc-audio]");
    if (!socketPath || !callButton) return;

    let socket;
    let reconnectTimer;
    let socketQueue = [];
    let peerConnection;
    let localStream;
    let activeCallId = "";
    let callState = "idle";
    let localMuted = false;
    let speakerEnabled = true;
    let pendingCandidates = [];
    let callStartedAt;
    let timer;

    const rtcConfiguration = {
      iceServers: [{urls: "stun:stun.l.google.com:19302"}],
    };

    function setStatus(message) {
      if (status) status.textContent = message;
    }

    function setMicStatus(message, active) {
      if (!micStatus) return;
      micStatus.textContent = message;
      micStatus.classList.toggle("is-active", Boolean(active));
    }

    function setButtonLabel(button, label) {
      if (!button) return;
      const labelElement = button.querySelector("small");
      if (labelElement) labelElement.textContent = label;
      else button.textContent = label;
    }

    function makeId() {
      return window.crypto && window.crypto.randomUUID
        ? window.crypto.randomUUID()
        : String(Date.now()) + "-" + Math.random().toString(16).slice(2);
    }

    function currentSocketPath() {
      if (!referralSelect || socketPath.indexOf("/0/") === -1) return socketPath;
      return socketPath.replace("/0/", "/" + referralSelect.value + "/");
    }

    function websocketUrl() {
      const protocol = window.location.protocol === "https:" ? "wss:" : "ws:";
      return protocol + "//" + window.location.host + currentSocketPath();
    }

    function sendSignal(kind, values) {
      const packet = {action: "rtc.signal", signal: Object.assign({kind: kind, call_id: activeCallId}, values || {})};
      if (socket && socket.readyState === WebSocket.OPEN) socket.send(JSON.stringify(packet));
      else socketQueue.push(packet);
    }

    function flushSocketQueue() {
      if (!socket || socket.readyState !== WebSocket.OPEN) return;
      socketQueue.splice(0).forEach(function (packet) { socket.send(JSON.stringify(packet)); });
    }

    function updateTimer() {
      if (!callStartedAt) {
        widget.querySelectorAll("[data-rtc-timer]").forEach(function (element) { element.textContent = "00:00"; });
        return;
      }
      const elapsed = Math.max(0, Math.floor((Date.now() - callStartedAt) / 1000));
      const minutes = Math.floor(elapsed / 60);
      const seconds = elapsed % 60;
      widget.querySelectorAll("[data-rtc-timer]").forEach(function (element) {
        element.textContent = String(minutes).padStart(2, "0") + ":" + String(seconds).padStart(2, "0");
      });
    }

    function updateControls() {
      const idle = callState === "idle";
      const incoming = callState === "incoming";
      const connected = callState === "connected";
      callButton.hidden = !idle;
      if (answerButton) answerButton.hidden = !incoming;
      if (declineButton) declineButton.hidden = !incoming;
      if (endButton) endButton.hidden = idle;
      if (muteButton) muteButton.hidden = !connected;
      if (speakerButton) speakerButton.hidden = !connected;
      widget.classList.toggle("is-incoming-call", incoming);
      widget.classList.toggle("is-call-active", !idle);
      if (callState === "outgoing") setStatus("Calling… waiting for the other participant to answer.");
      if (incoming) setStatus("Incoming voice call. Accept to activate your microphone.");
      if (connected) setStatus("Voice call connected.");
      if (idle) setStatus("Ready for a secure voice call.");
    }

    async function ensureLocalStream() {
      if (localStream) return localStream;
      if (!window.RTCPeerConnection) {
        throw new Error("This browser does not support live voice calls.");
      }
      if (!navigator.mediaDevices || !navigator.mediaDevices.getUserMedia) {
        throw new Error("This browser cannot access a microphone. Use HTTPS or a supported browser.");
      }
      localStream = await navigator.mediaDevices.getUserMedia({audio: true, video: false});
      localStream.getAudioTracks().forEach(function (track) { track.enabled = !localMuted; });
      setMicStatus("Microphone active", true);
      return localStream;
    }

    function createPeerConnection() {
      if (peerConnection) return peerConnection;
      peerConnection = new RTCPeerConnection(rtcConfiguration);
      if (localStream) localStream.getTracks().forEach(function (track) {
        peerConnection.addTrack(track, localStream);
      });
      peerConnection.addEventListener("icecandidate", function (event) {
        if (event.candidate) sendSignal("ice", {candidate: event.candidate});
      });
      peerConnection.addEventListener("track", function (event) {
        if (!remoteAudio) return;
        remoteAudio.srcObject = event.streams[0];
        remoteAudio.muted = !speakerEnabled;
        remoteAudio.play().catch(function () {
          setStatus("Tap the speaker control to start remote audio.");
        });
      });
      peerConnection.addEventListener("connectionstatechange", function () {
        if (!peerConnection) return;
        if (peerConnection.connectionState === "connected") {
          callState = "connected";
          callStartedAt = callStartedAt || Date.now();
          setMicStatus("Microphone active", true);
          updateControls();
        } else if (["failed", "closed"].includes(peerConnection.connectionState)) {
          setStatus("The voice connection ended. You can call again.");
          cleanup(false);
        } else if (peerConnection.connectionState === "disconnected") {
          setStatus("Voice connection interrupted. Reconnecting…");
        }
      });
      return peerConnection;
    }

    async function addLocalTracks() {
      const stream = await ensureLocalStream();
      const peer = createPeerConnection();
      const existingTrackIds = new Set(peer.getSenders().map(function (sender) {
        return sender.track && sender.track.id;
      }));
      stream.getTracks().forEach(function (track) {
        if (!existingTrackIds.has(track.id)) peer.addTrack(track, stream);
      });
      return peer;
    }

    async function startOutgoingCall() {
      if (callState !== "idle") return;
      try {
        activeCallId = makeId();
        await addLocalTracks();
        callState = "outgoing";
        callStartedAt = null;
        updateControls();
        sendSignal("invite");
      } catch (error) {
        activeCallId = "";
        cleanup(false);
        setStatus(error.message || "Microphone access was not granted.");
      }
    }

    async function acceptIncomingCall() {
      if (callState !== "incoming") return;
      try {
        await addLocalTracks();
        callState = "connected";
        callStartedAt = Date.now();
        sendSignal("accepted");
        updateControls();
      } catch (error) {
        setStatus(error.message || "Microphone access was not granted.");
      }
    }

    function declineIncomingCall() {
      if (!activeCallId) return;
      sendSignal("declined");
      cleanup(false);
    }

    async function handleSignal(signal) {
      if (!signal || !signal.kind) return;
      if (signal.kind === "invite") {
        if (callState !== "idle") return;
        activeCallId = signal.call_id;
        callState = "incoming";
        updateControls();
        return;
      }
      if (!activeCallId || signal.call_id !== activeCallId) return;
      if (signal.kind === "declined") {
        setStatus("The other participant declined the call.");
        cleanup(false);
        return;
      }
      if (signal.kind === "hangup") {
        setStatus("The other participant ended the call.");
        cleanup(false);
        return;
      }
      if (signal.kind === "accepted" && callState === "outgoing") {
        try {
          const peer = await addLocalTracks();
          const offer = await peer.createOffer({offerToReceiveAudio: true});
          await peer.setLocalDescription(offer);
          sendSignal("offer", {description: peer.localDescription});
        } catch (error) {
          setStatus(error.message || "The call could not start.");
          cleanup(false);
        }
        return;
      }
      if (signal.kind === "offer") {
        try {
          const peer = await addLocalTracks();
          await peer.setRemoteDescription(signal.description);
          pendingCandidates.splice(0).forEach(function (candidate) {
            peer.addIceCandidate(candidate).catch(function () {});
          });
          const answer = await peer.createAnswer();
          await peer.setLocalDescription(answer);
          sendSignal("answer", {description: peer.localDescription});
          callState = "connected";
          callStartedAt = callStartedAt || Date.now();
          updateControls();
        } catch (error) {
          setStatus(error.message || "The voice connection could not be established.");
          cleanup(false);
        }
        return;
      }
      if (signal.kind === "answer" && peerConnection) {
        await peerConnection.setRemoteDescription(signal.description);
      pendingCandidates.splice(0).forEach(function (candidate) {
        peerConnection.addIceCandidate(candidate).catch(function () {});
      });
        callState = "connected";
        callStartedAt = callStartedAt || Date.now();
        updateControls();
        return;
      }
      if (signal.kind === "ice" && signal.candidate) {
        if (!peerConnection || !peerConnection.remoteDescription) pendingCandidates.push(signal.candidate);
        else peerConnection.addIceCandidate(signal.candidate).catch(function () {});
      }
    }

    function cleanup(sendHangup) {
      if (sendHangup && activeCallId) sendSignal("hangup");
      if (peerConnection) {
        peerConnection.ontrack = null;
        peerConnection.close();
        peerConnection = null;
      }
      if (localStream) {
        localStream.getTracks().forEach(function (track) { track.stop(); });
        localStream = null;
      }
      if (remoteAudio) {
        remoteAudio.pause();
        remoteAudio.srcObject = null;
      }
      activeCallId = "";
      callState = "idle";
      localMuted = false;
      callStartedAt = null;
      pendingCandidates = [];
      setMicStatus("Microphone not connected", false);
      updateControls();
    }

    function connect() {
      if (!window.WebSocket || (socket && socket.readyState === WebSocket.OPEN)) return;
      socket = new WebSocket(websocketUrl());
      socket.addEventListener("open", function () {
        socket.send(JSON.stringify({action: "sync"}));
        flushSocketQueue();
      });
      socket.addEventListener("message", function (event) {
        let data;
        try { data = JSON.parse(event.data); } catch (error) { return; }
        if (data.type === "rtc.signal") handleSignal(data.signal).catch(function () {});
      });
      socket.addEventListener("close", function (event) {
        socket = null;
        if ([4001, 4403, 4404, 4409].includes(event.code)) {
          setStatus("The secure call channel is unavailable.");
          return;
        }
        window.clearTimeout(reconnectTimer);
        reconnectTimer = window.setTimeout(connect, 3000);
      });
    }

    callButton.addEventListener("click", startOutgoingCall);
    if (answerButton) answerButton.addEventListener("click", acceptIncomingCall);
    if (declineButton) declineButton.addEventListener("click", declineIncomingCall);
    if (endButton) endButton.addEventListener("click", function () {
      setStatus("Ending voice call…");
      cleanup(true);
    });
    if (muteButton) muteButton.addEventListener("click", function () {
      localMuted = !localMuted;
      if (localStream) localStream.getAudioTracks().forEach(function (track) { track.enabled = !localMuted; });
      muteButton.classList.toggle("active", localMuted);
      setButtonLabel(muteButton, localMuted ? "Unmute" : "Mute");
      setMicStatus(localMuted ? "Microphone muted" : "Microphone active", !localMuted);
    });
    if (speakerButton) speakerButton.addEventListener("click", function () {
      speakerEnabled = !speakerEnabled;
      if (remoteAudio) remoteAudio.muted = !speakerEnabled;
      speakerButton.classList.toggle("active", speakerEnabled);
      setButtonLabel(speakerButton, speakerEnabled ? "Speaker" : "Earpiece");
      if (speakerEnabled && remoteAudio) remoteAudio.play().catch(function () {});
    });
    if (referralSelect) referralSelect.addEventListener("change", function () {
      cleanup(true);
      if (socket) socket.close();
      window.setTimeout(connect, 100);
    });
    window.setInterval(updateTimer, 1000);
    window.addEventListener("beforeunload", function () {
      cleanup(true);
      window.clearTimeout(reconnectTimer);
      if (socket) socket.close();
    });

    updateControls();
    connect();
  });
}());
