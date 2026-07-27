"""Base85 BID encoding and monotonic increment."""

from __future__ import annotations

from pydantic import BaseModel, ConfigDict, field_validator


# Base85 alphabet (RFC 1924 style, 85 printable ASCII characters).
# Order matters: index 0 = '0', index 84 = '~'.
BASE85_ALPHABET = (
    "0123456789"
    "ABCDEFGHIJKLMNOPQRSTUVWXYZ"
    "abcdefghijklmnopqrstuvwxyz"
    "!#$%&()*+-;<=>?@^_`{|}~"
)
BASE85_RADIX = len(BASE85_ALPHABET)  # 85

# Base BIDs are exactly 5 Base85 characters.
BASE_BID_LENGTH = 5


class Base85BID(BaseModel):
    """A Base85-encoded BID.

    For base BIDs, value is exactly 5 Base85 chars.
    For sub-BIDs, value is one or more appended Base85 chars (validated separately).
    """

    model_config = ConfigDict(frozen=True)

    value: str

    @field_validator("value")
    @classmethod
    def _validate_base85(cls, v: str) -> str:
        if not v:
            raise ValueError("BID value cannot be empty")
        for ch in v:
            if ch not in BASE85_ALPHABET:
                raise ValueError(f"invalid Base85 character: {ch!r}")
        return v

    def increment(self) -> "Base85BID":
        """Return the next BID in the sequence (monotonic).

        Raises OverflowError if all digits are at the maximum alphabet value.
        """
        # Increment from the rightmost char; carry left on rollover.
        chars = list(self.value)
        i = len(chars) - 1
        while i >= 0:
            idx = BASE85_ALPHABET.index(chars[i])
            if idx < BASE85_RADIX - 1:
                chars[i] = BASE85_ALPHABET[idx + 1]
                return Base85BID(value="".join(chars))
            # Rollover: this char resets to 0, carry to the left.
            chars[i] = BASE85_ALPHABET[0]
            i -= 1
        # All digits rolled over — exhausted.
        raise OverflowError(f"BID space exhausted for value {self.value!r}")


def next_base_bid(highest: Base85BID | None) -> Base85BID:
    """Derive the next base-BID from the highest assigned (or zero if none).

    For base BIDs, the result is a 5-character Base85 string starting at '00000'
    if no BIDs have been assigned.
    """
    if highest is None:
        return Base85BID(value="0" * BASE_BID_LENGTH)
    # Pad/truncate to 5 chars for base-BID semantics.
    padded = highest.value.rjust(BASE_BID_LENGTH, BASE85_ALPHABET[0])[:BASE_BID_LENGTH]
    if len(padded) < BASE_BID_LENGTH:
        padded = padded.rjust(BASE_BID_LENGTH, BASE85_ALPHABET[0])
    return Base85BID(value=padded).increment()