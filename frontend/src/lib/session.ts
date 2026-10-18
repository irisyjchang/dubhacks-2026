export const skater = {
  name: "Iris",
  avatar: "/media/iris-avatar.jpg",
};

export const coach = {
  name: "Coach",
  avatar: "/media/coach-avatar.jpg",
  message:
    "Looks good! Your takeoff is getting more consistent. Let’s focus this week on holding your air position and checking the free leg.",
  time: "8:24 PM",
};

export const session = {
  jump: "3Lz",
  dateLabel: "Oct 14, 2024",
  timeLabel: "8:17 PM",
  duration: "00:12",
  currentTime: "0:04",
  image: "/media/skater-takeoff.jpg",
};

export const keyFrames = ["Approach", "Takeoff", "Air", "Landing", "Exit"] as const;

export const metrics = [
  {
    label: "Hip Position",
    grade: "B+",
    note: "Good position and height. Try to keep the free leg a bit higher in the last rotation.",
  },
  {
    label: "Shoulder Alignment",
    grade: "B",
    note: "Slightly early rotation.",
  },
  {
    label: "Free Leg Height",
    grade: "B-",
    note: "Could be higher.",
  },
  {
    label: "Rotation Speed",
    grade: "A-",
    note: "Consistent through air.",
  },
];

export const drills = [
  { title: "Edge Control Drills", detail: "3 sets · Off-ice → On-ice", done: true },
  { title: "Takeoff Consistency", detail: "4 sets · On-ice", done: true },
  { title: "Air Position Hold", detail: "3 sets · On-ice", done: false, current: true },
  { title: "Landing Stability", detail: "3 sets · On-ice", done: false },
  { title: "Full Jump Attempts", detail: "5–10 reps · On-ice", done: false },
];
