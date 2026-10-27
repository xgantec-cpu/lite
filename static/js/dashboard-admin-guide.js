(() => {
  const guide = document.querySelector("[data-admin-guide]");
  const userMenu = document.querySelector("[data-dashboard-user-menu]");
  if (!guide) return;

  const pageKey = guide.dataset.pageKey || document.body.dataset.dashboardPage || "dashboard";
  const userId = guide.dataset.userId || "unknown";
  const storageKey = `rapid-response-page-guide-seen:${userId}:${pageKey}`;
  const pageGuides = {
    dashboard_incoming: {
      kicker: "Incoming incidents · Page guide",
      title: "Review new emergency cases",
      description: "This is your attention queue. Cases assigned to your districts arrive here before they are opened or acted on.",
      steps: [["Start with unopened cases", "The unopened indicator shows which requests still need an initial response."], ["Open the full report", "Select a case to review its message, location, media, status, and response history."], ["Coordinate safely", "Use the case chat, notes, map, and referral tools to keep the response together."], ["Update the status", "Acknowledged or active cases leave the new attention area while remaining traceable."]],
      exampleTitle: "Example",
      example: "A new case from Masaka appears here for a responder assigned to Masaka. Open it, confirm the map, then acknowledge the request.",
      footer: "Only cases assigned or referred to you are shown.",
    },
    dashboard_home: {
      kicker: "Cases by district · Page guide",
      title: "Understand the response picture",
      description: "Use the district cards, live graph, map, and summary to compare active case volume and decide where attention is needed.",
      steps: [["Read the four counters", "The cards give a quick view of new, active, referred, and resolved work."], ["Compare district activity", "Use the chart and district cards to spot areas with rising case volume."], ["Open a district", "Select a district card to see its cases and map context without leaving the workspace."], ["Use the page guide again", "Open your user menu whenever you need a quick reminder of this page's purpose."]],
      exampleTitle: "Example",
      example: "If Masaka has a rising case count, open its district card to review the active cases and coordinate the next action.",
      footer: "The dashboard is limited to your assigned response areas.",
    },
    dashboard_area_activity: {
      kicker: "District activity · Page guide",
      title: "Compare district activity",
      description: "This view turns your assigned district data into a clear operational summary for faster decisions.",
      steps: [["Choose a period", "Use the available time controls to compare recent, monthly, or yearly activity."], ["Read the trend", "The volume chart shows whether incoming cases are increasing or easing."], ["Inspect the snapshot", "District cards and the map help connect the numbers to real response areas."], ["Open a case", "Select a district or case when the team needs the complete incident report."]],
      exampleTitle: "Example",
      example: "A sharp increase in one district is a signal to review its cases and coordinate additional response support.",
      footer: "Charts show live data available to your responder account.",
    },
    dashboard_global_map: {
      kicker: "Global case map · Page guide",
      title: "See cases and send verified alerts",
      description: "The map connects active cases to their reported locations. The alert panel is for verified public safety information only.",
      steps: [["Read the map markers", "Select a marker to open the related emergency report and its latest available location."], ["Fit the response area", "Use Fit all cases when you need a complete view of cases assigned to you."], ["Prepare an area alert", "Choose the audience, district, issue group, headline, and calm public message."], ["Send only verified information", "Do not include names, phone numbers, or exact private case details in a public alert."]],
      exampleTitle: "Example",
      example: "After confirming a verified safety issue affecting Masaka residents, select Masaka, write clear guidance, and send the public-safe notice.",
      footer: "Public alerts should be factual, necessary, and privacy-safe.",
    },
    inhouse_chat: {
      kicker: "In-house chat · Page guide",
      title: "Coordinate with officials",
      description: "Use this workspace for official responder communication without losing the case or district context.",
      steps: [["Choose a conversation", "Select the official or response group you need to contact."], ["Send a clear update", "Press Enter to send a message; use Shift+Enter when you need a new line."], ["Share supporting files", "Attach a relevant document, image, or audio note through the message composer."], ["Use calls when needed", "Start a browser call only when microphone permission and a reliable connection are available."]],
      exampleTitle: "Example",
      example: "Tell a police or hospital partner the case reference, current action, and the exact support needed—not private details unrelated to the response.",
      footer: "Keep official conversations focused on response work.",
    },
    dashboard_incident: {
      kicker: "Case report · Page guide",
      title: "Understand one emergency",
      description: "This page keeps the full case brief, map, communication, referrals, and response actions together.",
      steps: [["Read the emergency report", "Confirm the request reference, priority, message, contact, location, and submitted media."], ["Check the map", "Use the tracked coordinates and location trail only when the data is available and authorized."], ["Coordinate the response", "Chat with officials, add operational notes, and update the case status."], ["Refer when needed", "Send the case to the correct hospital, police station, or responder while keeping its history attached."]],
      exampleTitle: "Example",
      example: "A responder opens a Masaka case, confirms the reported location, contacts the sender, and refers it to the appropriate police station if required.",
      footer: "Do not share case details outside approved response channels.",
    },
    dashboard_referral_create: {
      kicker: "Case transfer · Page guide",
      title: "Send a focused referral",
      description: "Use this page to transfer responsibility to the right official or institution without losing the case context.",
      steps: [["Choose the destination", "Select an admin, police station, hospital, person, or organization."], ["Choose the transfer mode", "Use the available in-app or external channel that fits the response."], ["Enter only needed details", "Complete the fields required for the selected destination and avoid unrelated private data."], ["Confirm the handoff", "Send the referral and keep the same case reference for later tracking."]],
      exampleTitle: "Example",
      example: "For a hospital referral, choose the destination district and hospital, include the case context and coordinates, then send the in-app handoff.",
      footer: "A referral should be specific, necessary, and traceable.",
    },
    access_denied: {
      kicker: "Access notice · Page guide",
      title: "Request the correct access",
      description: "This notice appears when a case is outside your current district assignment or referral permissions.",
      steps: [["Read the reason", "The notice explains why the case could not be opened from your current account."], ["Contact the district responder", "Ask the assigned district admin to review or refer the case to you."], ["Use a valid token", "Open the case with an approved referral token when one is issued."], ["Return safely", "Use the back link to continue working only on cases assigned to you."]],
      exampleTitle: "Example",
      example: "If a case belongs to another district, request a referral rather than attempting to bypass the assignment boundary.",
      footer: "Access controls protect the sender and the response team.",
    },
    dashboard_cases: {
      kicker: "Cases archive · Page guide",
      title: "Find completed response work",
      description: "The archive keeps resolved cases and public alert history available for review, reporting, and accountability.",
      steps: [["Search the archive", "Use the available filters or case reference to find a previous response."], ["Review the full record", "Open a case to see its status, notes, referrals, communication, and location data."], ["Check public alerts", "Review notices sent to a district or the whole country in the alert archive."], ["Generate a report", "Use Print report to choose the case or alert information to save as a PDF."]],
      exampleTitle: "Example",
      example: "A resolved emergency can be reopened from the archive to confirm the action history before a review meeting.",
      footer: "Archive access still follows your responder permissions.",
    },
    dashboard_favorites: {
      kicker: "Favorites · Page guide",
      title: "Keep priority cases close",
      description: "Favorites is your private shortlist for cases that need quick follow-up or contain important clues.",
      steps: [["Unlock the page", "Enter the private Favorites passcode configured in your profile."], ["Review saved cases", "Open a favorite to return to its full report and current status."], ["Use notes for clues", "Add concise operational notes that help the next response decision."], ["Remove old favorites", "Unfavorite cases when they no longer need priority attention."]],
      exampleTitle: "Example",
      example: "Keep a case with an important referral or follow-up clue in Favorites until the receiving team confirms action.",
      footer: "Favorites are private to your responder account.",
    },
    dashboard_referral_inbox: {
      kicker: "Referral inbox · Page guide",
      title: "Receive transferred cases",
      description: "Cases referred to you appear here so you can accept the handoff, review the context, and continue the response.",
      steps: [["Check new referrals", "Unread referrals show cases that still need your attention."], ["Read the handoff", "Review the sender's message, destination, map, case history, and attachments."], ["Continue the response", "Open the case to chat, update status, add notes, or make another referral."], ["Keep the same reference", "A referral moves responsibility while preserving the case identity and history."]],
      exampleTitle: "Example",
      example: "A district responder can refer a case to a police station while the same emergency reference and location remain connected.",
      footer: "A referral changes responsibility, not the case history.",
    },
    dashboard_referral_token: {
      kicker: "Referral token · Page guide",
      title: "Open an approved handoff",
      description: "Use a referral token when an authorized official needs to open a case outside their normal district assignment.",
      steps: [["Confirm the token", "Use the secure token supplied by the referring district responder."], ["Open the case", "Enter the token exactly as provided and review the case identity before acting."], ["Protect the handoff", "Do not share a referral token in a public message or with an unapproved person."], ["Continue in the case", "Use the case tools for chat, status updates, tracking, and further referrals."]],
      exampleTitle: "Example",
      example: "A hospital officer uses a valid referral token to open the case that the district team intentionally transferred for treatment.",
      footer: "Tokens grant limited access to an approved case.",
    },
    operations_center: {
      kicker: "Operations Center · Page guide",
      title: "Review the full response network",
      description: "This restricted view helps parent administrators search and compare cases across the response network.",
      steps: [["Unlock the center", "Enter the level-five passcode configured by the parent administrator."], ["Choose a district", "Open a district card to see its numbered cases and current activity."], ["Search carefully", "Use case numbers and district filters to locate a record quickly."], ["Protect the view", "Lock the center again when you finish reviewing sensitive cross-district data."]],
      exampleTitle: "Example",
      example: "A parent administrator can compare cases across districts during a coordination meeting without changing the assigned responder workflow.",
      footer: "This view contains broader and more sensitive operational data.",
    },
    admin_section_gate: {
      kicker: "Main administration · Page guide",
      title: "Unlock administration safely",
      description: "This gate protects parent administrator settings such as users, district assignments, institutions, and system controls.",
      steps: [["Confirm your authority", "Only an approved parent administrator should use this section."], ["Enter the private password", "Use the administration password configured for this deployment."], ["Manage assignments", "Create, deactivate, and assign responder or institution accounts from Django administration."], ["Lock the area again", "Sign out when finished and never share the administration password."]],
      exampleTitle: "Example",
      example: "A parent administrator assigns four districts to a responder so incoming cases route to the correct official.",
      footer: "Administration access can change the whole response network.",
    },
    dashboard_profile: {
      kicker: "Responder profile · Page guide",
      title: "Manage your responder access",
      description: "Your profile shows the districts assigned to you and the private tools configured for your account.",
      steps: [["Confirm assignments", "Check that the districts shown match the areas you are responsible for."], ["Set private tools", "Configure the Favorites passcode and review the account protection options."], ["Enable MFA", "Use an authenticator app to add a second sign-in check before production access."], ["Report a mismatch", "Ask the parent administrator to correct district assignments or access settings."]],
      exampleTitle: "Example",
      example: "If you handle Masaka, Mbarara, and two other districts, only those assignments should appear in your responder workspace.",
      footer: "Access follows the assignments set by the parent administrator.",
    },
    dashboard: {
      kicker: "Responder quick start",
      title: "Welcome to Rapid Response",
      description: "This short guide shows the normal journey of an emergency case through your workspace.",
      steps: [["Check Incoming incidents", "New cases assigned to your districts appear here first."], ["Open and understand the case", "Review the message, location, map, media, notes, and live status."], ["Coordinate the response", "Use chat, files, calls, referrals, and status updates to keep everyone aligned."], ["Close the loop", "Resolved cases leave the attention queue and remain available in the archive and reports."]],
      exampleTitle: "Simple example",
      example: "A case from Masaka is routed to a responder assigned to Masaka. If police support is needed, refer it to the correct station and continue tracking the same case reference.",
      footer: "Only cases assigned or referred to you are shown.",
    },
  };

  const pageGuide = pageGuides[pageKey] || pageGuides.dashboard;
  const title = guide.querySelector("#admin-guide-title");
  const description = guide.querySelector("#admin-guide-description");
  const kicker = guide.querySelector("[data-guide-kicker]");
  const stepList = guide.querySelector("[data-guide-steps]");
  const exampleTitle = guide.querySelector("[data-guide-example-title]");
  const exampleCopy = guide.querySelector("[data-guide-example-copy]");
  const footerNote = guide.querySelector("[data-guide-footer-note]");
  const guideIcon = guide.querySelector(".admin-guide-icon");

  title.textContent = pageGuide.title;
  description.textContent = pageGuide.description;
  kicker.textContent = pageGuide.kicker;
  exampleTitle.textContent = pageGuide.exampleTitle;
  exampleCopy.textContent = pageGuide.example;
  footerNote.textContent = pageGuide.footer;
  guideIcon.textContent = pageKey === "dashboard_global_map" ? "⌖" : pageKey === "inhouse_chat" ? "⌁" : "?";
  stepList.replaceChildren(...pageGuide.steps.map((step, stepIndex) => {
    const item = document.createElement("li");
    const number = document.createElement("b");
    const content = document.createElement("span");
    const stepTitle = document.createElement("strong");
    const stepDescription = document.createElement("small");
    number.textContent = String(stepIndex + 1);
    stepTitle.textContent = step[0];
    stepDescription.textContent = step[1];
    content.append(stepTitle, stepDescription);
    item.append(number, content);
    return item;
  }));

  const closeUserMenu = () => {
    if (!userMenu) return;
    const toggle = userMenu.querySelector("[data-dashboard-user-toggle]");
    const panel = userMenu.querySelector("[data-dashboard-user-panel]");
    toggle.setAttribute("aria-expanded", "false");
    panel.hidden = true;
  };

  const openGuide = () => {
    closeUserMenu();
    guide.hidden = false;
    document.body.classList.add("admin-guide-open");
  };

  const closeGuide = () => {
    guide.hidden = true;
    document.body.classList.remove("admin-guide-open");
    try { window.localStorage.setItem(storageKey, "1"); } catch (error) {}
  };

  guide.querySelectorAll("[data-admin-guide-close]").forEach((button) => button.addEventListener("click", closeGuide));
  guide.addEventListener("click", (event) => {
    if (event.target === guide) closeGuide();
  });

  if (userMenu) {
    const userToggle = userMenu.querySelector("[data-dashboard-user-toggle]");
    const userPanel = userMenu.querySelector("[data-dashboard-user-panel]");
    userToggle.addEventListener("click", () => {
      const isOpen = userToggle.getAttribute("aria-expanded") === "true";
      userToggle.setAttribute("aria-expanded", String(!isOpen));
      userPanel.hidden = isOpen;
    });
    userMenu.querySelectorAll("[data-admin-guide-open]").forEach((button) => button.addEventListener("click", openGuide));
    document.addEventListener("click", (event) => {
      if (!userMenu.contains(event.target)) closeUserMenu();
    });
  }

  document.addEventListener("keydown", (event) => {
    if (event.key !== "Escape") return;
    if (!guide.hidden) closeGuide();
    else closeUserMenu();
  });

  let alreadySeen = false;
  try { alreadySeen = window.localStorage.getItem(storageKey) === "1"; } catch (error) {}
  if (!alreadySeen) openGuide();
})();
