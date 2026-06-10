// Shared dark map styling, carved verbatim from the legacy monolith.
export const darkMapStyles = [
  { elementType: "geometry", stylers: [{ color: "#0d1326" }] },
  { elementType: "labels.text.stroke", stylers: [{ color: "#0d1326" }] },
  { elementType: "labels.text.fill", stylers: [{ color: "#596f90" }] },
  {
    featureType: "administrative.locality",
    elementType: "labels.text.fill",
    stylers: [{ color: "#8a9eb8" }],
  },
  {
    featureType: "poi",
    elementType: "labels.text.fill",
    stylers: [{ color: "#8a9eb8" }],
  },
  {
    featureType: "poi.park",
    elementType: "geometry",
    stylers: [{ color: "#111b30" }],
  },
  {
    featureType: "poi.park",
    elementType: "labels.text.fill",
    stylers: [{ color: "#3b537a" }],
  },
  {
    featureType: "road",
    elementType: "geometry",
    stylers: [{ color: "#1b253b" }],
  },
  {
    featureType: "road",
    elementType: "geometry.stroke",
    stylers: [{ color: "#151e30" }],
  },
  {
    featureType: "road",
    elementType: "labels.text.fill",
    stylers: [{ color: "#4f6585" }],
  },
  {
    featureType: "road.highway",
    elementType: "geometry",
    stylers: [{ color: "#24324f" }],
  },
  {
    featureType: "road.highway",
    elementType: "geometry.stroke",
    stylers: [{ color: "#151e30" }],
  },
  {
    featureType: "road.highway",
    elementType: "labels.text.fill",
    stylers: [{ color: "#6b82a3" }],
  },
  {
    featureType: "water",
    elementType: "geometry",
    stylers: [{ color: "#172d54" }],
  },
  {
    featureType: "water",
    elementType: "labels.text.fill",
    stylers: [{ color: "#3b537a" }],
  },
  {
    featureType: "water",
    elementType: "labels.text.stroke",
    stylers: [{ color: "#172d54" }],
  },
];
