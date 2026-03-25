// SPDX-License-Identifier: BUSL-1.1
pragma solidity >=0.7.6;

import {CommonDeploy} from "./CommonDeploy.sol";
import {SiloVirtualAssetUSD} from "silo-oracles/contracts/silo-virtual-assets/SiloVirtualAssetUSD.sol";
import {SiloVirtualAssetEUR} from "silo-oracles/contracts/silo-virtual-assets/SiloVirtualAssetEUR.sol";
import {SiloVirtualAssetBTC} from "silo-oracles/contracts/silo-virtual-assets/SiloVirtualAssetBTC.sol";
import {SiloOraclesContracts} from "./SiloOraclesContracts.sol";

/*
    FOUNDRY_PROFILE=oracles \
        forge script silo-oracles/deploy/SiloVirtualAssetsDeploy.s.sol \
        --ffi --rpc-url $RPC_ARBITRUM --broadcast --verify

    Resume verification:
    FOUNDRY_PROFILE=oracles \
        forge script silo-oracles/deploy/SiloVirtualAssetsDeploy.s.sol \
        --ffi --rpc-url $RPC_INK \
        --verify \
        --verifier blockscout \
        --verifier-url $VERIFIER_URL_INK \
        --private-key $PRIVATE_KEY \
        --resume

    FOUNDRY_PROFILE=oracles forge verify-contract <contract-address> \
        silo-oracles/contracts/silo-virtual-assets/SiloVirtualAsset8Decimals.sol:SiloVirtualAsset8Decimals \
        --verifier blockscout \
        --verifier-url $VERIFIER_URL_INK \
        --compiler-version 0.8.28 \
        --num-of-optimizations 200 \
        --watch
 */
contract SiloVirtualAssetsDeploy is CommonDeploy {
    function run() public {
        uint256 deployerPrivateKey = uint256(vm.envBytes32("PRIVATE_KEY"));

        vm.startBroadcast(deployerPrivateKey);

        address usdAsset = address(new SiloVirtualAssetUSD());
        address eurAsset = address(new SiloVirtualAssetEUR());
        address btcAsset = address(new SiloVirtualAssetBTC());

        vm.stopBroadcast();

        _registerDeployment(usdAsset, SiloOraclesContracts.SILO_VIRTUAL_ASSET_USD);
        _registerDeployment(eurAsset, SiloOraclesContracts.SILO_VIRTUAL_ASSET_EUR);
        _registerDeployment(btcAsset, SiloOraclesContracts.SILO_VIRTUAL_ASSET_BTC);
    }
}
