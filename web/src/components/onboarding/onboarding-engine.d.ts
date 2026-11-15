/** What onboarding learns about the student. Saved in the browser; there is no profile API yet. */
export type ProfileAnswers = {
  name: string;
  email: string;
  area: string;
  moveIn: string | null;
  firstTimeInUK: boolean;
};

/** What the new-case flow learns about one place. */
export type CaseAnswers = {
  listingUrl: string;
  listingSite: string;
  address: string;
  rent: string;
  agency: string;
  companyNumber: string;
  agentName: string;
  seenInPerson: "Yes" | "No" | "Video call only" | null;
  askedToPay: "No" | "Holding deposit" | "Deposit or rent upfront" | null;
  paidAlready: boolean;
  files: string[];
  risky: boolean;
};

/** The listing fields the new-case flow can prefill (see `ListingPreview` in lib/api). */
export type ListingPreviewLike = {
  status: string;
  platform?: string | null;
  address?: string | null;
  rent_pcm?: number | null;
  agency_name?: string | null;
  company_number?: string | null;
  landlord_name?: string | null;
};

export type UploadKey = "messages" | "contract" | "video" | "emails" | "payment";
export type OnboardingFiles = Partial<Record<UploadKey, File>>;

export function startWardenOnboarding(
  root: HTMLElement,
  opts: {
    mode: "onboarding" | "newcase";
    icons: Record<string, string>;
    initialName?: string;
    profile?: Partial<ProfileAnswers>;
    onFinish: (answers: ProfileAnswers | CaseAnswers, files: OnboardingFiles) => Promise<void> | void;
    onCancel?: () => void;
    /** Reads a listing link so its details can prefill the form; null when it cannot. */
    previewListing?: (url: string) => Promise<ListingPreviewLike | null>;
  },
): () => void;
