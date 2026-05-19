// SPDX-License-Identifier: MIT
pragma solidity 0.8.28;

interface IPancakeV3Pool {
    function swap(
        address recipient,
        bool zeroForOne,
        int256 amountSpecified,
        uint160 sqrtPriceLimitX96,
        bytes calldata data
    ) external returns (int256 amount0, int256 amount1);
}

contract PancakeV3SwapExecutor {
    address public immutable owner;

    error NotOwner();
    error InvalidCallback();
    error TransferFailed();

    constructor() {
        owner = msg.sender;
    }

    function swap(
        address pool,
        address recipient,
        bool zeroForOne,
        int256 amountSpecified,
        uint160 sqrtPriceLimitX96,
        address inToken
    ) external returns (int256 amount0, int256 amount1) {
        if (msg.sender != owner) revert NotOwner();

        assembly {
            tstore(0, pool)
            tstore(1, inToken)
        }

        (amount0, amount1) = IPancakeV3Pool(pool).swap(
            recipient,
            zeroForOne,
            amountSpecified,
            sqrtPriceLimitX96,
            ""
        );
    }

    function pancakeV3SwapCallback(int256 amount0Delta, int256 amount1Delta, bytes calldata) external {
        address expectedPool;
        address inToken;
        assembly {
            expectedPool := tload(0)
            inToken := tload(1)
            // one-shot: clear so a re-entrant callback in the same tx reverts
            tstore(0, 0)
        }

        if (msg.sender != expectedPool) revert InvalidCallback();

        uint256 owed = amount0Delta > 0 ? uint256(amount0Delta) : uint256(amount1Delta);
        _safeTransfer(inToken, msg.sender, owed);
    }

    function withdraw(address token, address to, uint256 amount) external {
        if (msg.sender != owner) revert NotOwner();
        _safeTransfer(token, to, amount);
    }

    function _safeTransfer(address token, address to, uint256 amount) private {
        bool ok;
        assembly {
            let ptr := mload(0x40)
            mstore(ptr, 0xa9059cbb00000000000000000000000000000000000000000000000000000000)
            mstore(add(ptr, 0x04), to)
            mstore(add(ptr, 0x24), amount)
            let success := call(gas(), token, 0, ptr, 0x44, 0, 0x20)
            let returnedTrue := and(eq(returndatasize(), 0x20), eq(mload(0), 1))
            ok := and(success, or(iszero(returndatasize()), returnedTrue))
        }
        if (!ok) revert TransferFailed();
    }
}
