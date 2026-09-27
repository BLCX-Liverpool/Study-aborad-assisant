import { useRef, useState } from "react";
import { Loader2, Upload } from "lucide-react";
import { uploadFile } from "../lib/api";
import type { UploadedFile } from "../types";

type FileUploaderProps = {
  userId: string;
  onUploaded: (file: UploadedFile) => void;
};

export function FileUploader({ userId, onUploaded }: FileUploaderProps) {
  const inputRef = useRef<HTMLInputElement | null>(null);
  const [isUploading, setIsUploading] = useState(false);
  const [error, setError] = useState<string | null>(null);

  async function handleFile(file: File | undefined) {
    if (!file) return;
    setIsUploading(true);
    setError(null);
    try {
      const uploaded = await uploadFile({ file, userId });
      onUploaded(uploaded);
    } catch (caught) {
      setError(caught instanceof Error ? caught.message : "Upload failed");
    } finally {
      setIsUploading(false);
    }
  }

  return (
    <div className="uploader">
      <input
        ref={inputRef}
        type="file"
        accept=".pdf,.docx,.pptx"
        onChange={(event) => void handleFile(event.target.files?.[0])}
      />
      <button
        className="secondary-button"
        type="button"
        onClick={() => inputRef.current?.click()}
        disabled={isUploading}
      >
        {isUploading ? <Loader2 className="spin" size={16} /> : <Upload size={16} />}
        Select document
      </button>
      {error ? <p className="error-text">{error}</p> : null}
    </div>
  );
}

