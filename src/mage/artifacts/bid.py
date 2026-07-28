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

    @classmethod
    def parse(cls, value: str) -> "Base85BID":
        """Validate and construct a Base85BID from a string."""
        return cls(value=value)

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

    @classmethod
    def derive(cls, parent: "Base85BID", scenario_index: int) -> "Base85BID":
        """Derive a sub-BID by appending a Base85-encoded scenario_index to parent.

        The result is parent.value + encode_base85(scenario_index). The encoding
        is the shortest natural Base85 representation with no leading zeros
        (i.e., index 0 → "0", index 1 → "1", ..., index 84 → "~", index 85 → "10").
        """
        if scenario_index < 0:
            raise ValueError(f"scenario_index must be non-negative; got {scenario_index}")

        if scenario_index == 0:
            suffix = BASE85_ALPHABET[0]  # "0"
        else:
            # Convert to Base85 with no leading zeros.
            digits: list[int] = []
            n = scenario_index
            while n > 0:
                digits.append(n % BASE85_RADIX)
                n //= BASE85_RADIX
            digits.reverse()
            suffix = "".join(BASE85_ALPHABET[d] for d in digits)

        return cls(value=parent.value + suffix)


def next_base_bid(highest: Base85BID | None) -> Base85BID:
    """Derive the next base-BID from the highest assigned (or zero if none).

    For base BIDs, the result is a 5-character Base85 string starting at '00000'
    if no BIDs have been assigned.
    """
    if highest is None:
        return Base85BID(value="0" * BASE_BID_LENGTH)
    # Pad/truncate to 5 chars for base-BID semantics.
    padded = highest.value.rjust(BASE_BID_LENGTH, BASE85_ALPHABET[0])
    return Base85BID(value=padded).increment()
