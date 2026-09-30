export const JOB_TYPE_OPTIONS = [
  { value: "auto", label: "Use role keywords" },
  { value: "any", label: "Any job type" },
  { value: "full_time", label: "Full-time" },
  { value: "part_time", label: "Part-time" },
  { value: "internship", label: "Internship" },
  { value: "co_op", label: "Co-op" },
  { value: "contract", label: "Contract / freelance" },
  { value: "temporary", label: "Temporary / seasonal" },
] as const;

export type JobType = (typeof JOB_TYPE_OPTIONS)[number]["value"];

export const jobTypeLabel = (value: JobType) =>
  JOB_TYPE_OPTIONS.find((option) => option.value === value)?.label ?? value;
